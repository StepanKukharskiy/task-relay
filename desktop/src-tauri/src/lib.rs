use serde_json::Value;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri_plugin_opener::OpenerExt;

const ACTIONS: &[&str] = &["status", "project", "provider", "telegram", "update-check",
    "channel-update", "channel-status",
    "companion-status", "conversation", "approval-detail", "messages-start", "messages-stop",
    "handoff-prepare", "handoff-apply", "handoff-status", "handoff-restore",
    "service-status", "service-start", "service-stop", "service-connect", "service-disconnect",
    "tasks", "task-detail", "task-create", "task-send", "task-send-file", "task-stop", "task-approval-decide",
    "plans", "plan-create", "plan-detail", "plan-prepare", "plan-decide",
    "workflows", "automation-tools", "approval-inbox", "usage-summary", "storage-breakdown", "cleanup-preview", "cleanup-apply"];

fn bridge_command(app: &tauri::AppHandle) -> Result<Command, String> {
    if cfg!(debug_assertions) {
        let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let mut command = Command::new("python3");
        command.args(["-m", "task_relay.desktop_bridge"]);
        command.current_dir(source);
        command.env("TASK_RELAY_DESKTOP_RUNTIME_ROOT",
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/runtime"));
        command.env("PYTHONDONTWRITEBYTECODE", "1");
        return Ok(command);
    }
    let root = app.path().resource_dir().map_err(|_| "Bundled runtime is unavailable.")?
        .join("resources").join("runtime");
    let python = root.join("python").join("bin").join("python3");
    let entry = root.join("app").join("desktop_bridge_entry.py");
    if !python.is_file() || !entry.is_file() {
        return Err("Bundled Task Relay runtime is missing. Reinstall the desktop app.".into());
    }
    let mut command = Command::new(python);
    command.arg(entry).current_dir(root.join("app"));
    command.env("TASK_RELAY_DESKTOP_RUNTIME_ROOT", root);
    command.env("PYTHONNOUSERSITE", "1");
    command.env("PYTHONDONTWRITEBYTECODE", "1");
    command.env_remove("PYTHONPATH").env_remove("PYTHONHOME");
    Ok(command)
}

fn execute(app: tauri::AppHandle, path: String, value: Value) -> Result<Value, String> {
    if !ACTIONS.contains(&path.as_str()) {
        return Err("Unknown setup action.".into());
    }
    let body = serde_json::to_vec(&value).map_err(|_| "Invalid setup request.")?;
    if body.len() > 16384 {
        return Err("Request is too large.".into());
    }
    run_bridge(bridge_command(&app)?, &path, &body)
}

fn run_bridge(mut command: Command, path: &str, body: &[u8]) -> Result<Value, String> {
    command.arg(path).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    let mut child = command.spawn().map_err(|_| "Task Relay runtime could not start.")?;
    child.stdin.take().ok_or("Task Relay runtime input is unavailable.")?
        .write_all(&body).map_err(|_| "Task Relay runtime input failed.")?;
    let mut stdout = child.stdout.take().ok_or("Task Relay runtime output is unavailable.")?;
    let reader = std::thread::spawn(move || {
        let mut output = Vec::new();
        let mut buffer = [0_u8; 8192];
        let mut oversized = false;
        loop {
            let count = stdout.read(&mut buffer)?;
            if count == 0 { break; }
            let remaining = 1_000_000_usize.saturating_sub(output.len());
            oversized |= count > remaining;
            output.extend_from_slice(&buffer[..count.min(remaining)]);
        }
        Ok::<_, std::io::Error>((output, oversized))
    });
    // Lifecycle operations journal their intent and wait for a fresh heartbeat.
    // Do not kill them at the ordinary read deadline while they are restoring a service.
    let seconds = if matches!(path, "service-start" | "messages-start" | "handoff-apply" | "handoff-restore") { 90 } else { 15 };
    let deadline = Instant::now() + Duration::from_secs(seconds);
    loop {
        if child.try_wait().map_err(|_| "Task Relay runtime did not finish.")?.is_some() {
            break;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            let _ = reader.join();
            return Err(if seconds > 15 {
                "The service action did not confirm completion. Inspect the handoff receipt and service status before another action; it will not be replayed."
            } else {
                "Task Relay could not read its local data in time. Check this app’s access to the selected data folder, then refresh status."
            }.into());
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let (output, oversized) = reader.join()
        .map_err(|_| "Task Relay runtime output stopped unexpectedly.")?
        .map_err(|_| "Task Relay runtime output could not be read.")?;
    if oversized {
        return Err("Task Relay runtime returned too much data.".into());
    }
    let response: Value = serde_json::from_slice(&output)
        .map_err(|_| "Task Relay runtime returned an invalid result.")?;
    if response.get("ok").and_then(Value::as_bool) == Some(true) {
        response.get("value").cloned().ok_or("Task Relay runtime returned no result.".into())
    } else {
        Err(response.get("error").and_then(Value::as_str)
            .unwrap_or("Task Relay setup could not finish.").to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn large_valid_bridge_reply_drains_without_stalling() {
        let mut command = Command::new("python3");
        command.args(["-c", "import json,sys;sys.stdin.buffer.read();print(json.dumps({'ok':True,'value':{'data':'x'*200000}}))"]);
        let result = run_bridge(command, "status", b"{}").unwrap();
        assert_eq!(result["data"].as_str().unwrap().len(), 200_000);
    }
}

#[tauri::command]
async fn relay_request(app: tauri::AppHandle, path: String, value: Value) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || execute(app, path, value)).await
        .map_err(|_| "Task Relay runtime stopped unexpectedly.".to_string())?
}

#[tauri::command]
async fn companion_open(app: tauri::AppHandle, target: String) -> Result<(), String> {
    let url = match target.as_str() {
        "conversation" => {
            let handle = app.clone();
            let result = tauri::async_runtime::spawn_blocking(move || execute(handle, "conversation".into(), serde_json::json!({})))
                .await.map_err(|_| "Could not read the saved conversation.")??;
            result["url"].as_str().ok_or("Connect Telegram in Settings first.")?.to_owned()
        },
        "messages" => "sms:".to_owned(),
        "permissions" => "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles".to_owned(),
        _ => return Err("Unknown companion destination.".into()),
    };
    app.opener().open_url(url, None::<&str>).map_err(|_| "Could not open the selected app.".into())
}

fn show_companion(app: &tauri::AppHandle, destination: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
        let _ = window.emit("companion-navigate", destination);
    }
}

#[tauri::command]
fn companion_data_location(app: tauri::AppHandle) -> Result<String, String> {
    // Resolve the saved name without stat'ing protected Documents from a child
    // process. The user's native folder selection supplies macOS access; it does
    // not modify the binding or grant arbitrary worker file permissions.
    if let Ok(path) = std::env::var("TASK_RELAY_DATA_DIR") {
        if PathBuf::from(&path).is_absolute() { return Ok(path); }
    }
    let home = app.path().home_dir().map_err(|_| "Home directory is unavailable.")?;
    let binding = home.join("Library/Application Support/Task Relay Desktop/binding.json");
    if let Ok(raw) = std::fs::read(binding) {
        if let Ok(value) = serde_json::from_slice::<Value>(&raw) {
            if let Some(path) = value["TASK_RELAY_DATA_DIR"].as_str() {
                if PathBuf::from(path).is_absolute() { return Ok(path.to_owned()); }
            }
        }
    }
    Ok(home.join(".task-relay").to_string_lossy().into_owned())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| show_companion(app, "home")))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let status = MenuItem::with_id(app, "home", "Connection status…", true, None::<&str>)?;
            let chat = MenuItem::with_id(app, "conversation", "Open Telegram", true, None::<&str>)?;
            let review = MenuItem::with_id(app, "review", "Review decisions…", true, None::<&str>)?;
            let settings = MenuItem::with_id(app, "settings", "Settings…", true, None::<&str>)?;
            let channels = MenuItem::with_id(app, "channels", "Channels…", true, None::<&str>)?;
            let pause = MenuItem::with_id(app, "pause-messaging", "Pause all messaging", true, None::<&str>)?;
            let separator = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "Quit companion (Relay stays running)", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&status, &chat, &review, &channels, &pause, &settings, &separator, &quit])?;
            TrayIconBuilder::with_id("relay-companion")
                .icon(tauri::include_image!("icons/menu-template.png"))
                .icon_as_template(true)
                .tooltip("Task Relay")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| {
                    if event.id.as_ref() == "quit" { app.exit(0); }
                    else { show_companion(app, event.id.as_ref()); }
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![relay_request, companion_open, companion_data_location])
        .build(tauri::generate_context!())
        .expect("Task Relay desktop window failed to start")
        .run(|app, event| {
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = event {
                show_companion(app, "home");
            }
            #[cfg(not(target_os = "macos"))]
            let _ = (app, event);
        });
}
