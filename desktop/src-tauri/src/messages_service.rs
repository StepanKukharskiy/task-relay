//! Messages runs as this application's own executable, without a second bundle.
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

static STOP: AtomicBool = AtomicBool::new(false);
extern "C" fn stop(_: i32) { STOP.store(true, Ordering::SeqCst); }

fn runtime(executable: &Path) -> Result<PathBuf, String> {
    let macos = executable.parent().ok_or("Missing executable folder")?;
    if macos.file_name().and_then(|s| s.to_str()) != Some("MacOS") {
        return Err("Messages service must run from Task Relay.app".into());
    }
    Ok(macos.parent().ok_or("Missing Contents folder")?.join("Resources/resources/runtime"))
}

pub fn run() -> Result<i32, String> {
    let root = runtime(&std::env::current_exe().map_err(|e| e.to_string())?)?;
    let python = root.join("python/bin/python3");
    let source = root.join("app");
    if !python.is_file() || !source.join("messages_pilot.py").is_file() {
        return Err("Task Relay's Messages runtime is missing".into());
    }
    let data = std::env::var("TASK_RELAY_DATA_DIR").map_err(|_| "Messages needs its saved Relay data binding")?;
    if !Path::new(&data).is_absolute() { return Err("Invalid Relay data binding".into()); }
    let paused = Path::new(&data).join("messages-pilot/paused");
    unsafe { libc::signal(libc::SIGTERM, stop as *const () as usize); libc::signal(libc::SIGINT, stop as *const () as usize); }
    while paused.exists() && !STOP.load(Ordering::SeqCst) { std::thread::sleep(Duration::from_millis(250)); }
    if STOP.load(Ordering::SeqCst) { return Ok(0); }
    let mut child = Command::new(python).arg(source.join("messages_pilot.py")).arg("--background")
        .current_dir(source).stdin(Stdio::null())
        .env("TASK_RELAY_MESSAGES_OWNER", "task-relay-app")
        .env("TASK_RELAY_COMPANION", "1")
        .env("PYTHONUNBUFFERED", "1").env("PYTHONNOUSERSITE", "1").env("PYTHONDONTWRITEBYTECODE", "1")
        .env_remove("PYTHONHOME").env_remove("PYTHONPATH")
        .env("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin")
        .spawn().map_err(|e| e.to_string())?;
    loop {
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? { return Ok(status.code().unwrap_or(1)); }
        if STOP.load(Ordering::SeqCst) || paused.exists() {
            unsafe { libc::kill(child.id() as i32, libc::SIGTERM); }
            let deadline = Instant::now() + Duration::from_secs(10);
            while Instant::now() < deadline {
                if child.try_wait().map_err(|e| e.to_string())?.is_some() { return Ok(0); }
                std::thread::sleep(Duration::from_millis(100));
            }
            let _ = child.kill(); let _ = child.wait(); return Ok(0);
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn resolves_only_own_bundle() {
        assert_eq!(runtime(Path::new("/Applications/Task Relay.app/Contents/MacOS/task-relay-desktop")).unwrap(),
            PathBuf::from("/Applications/Task Relay.app/Contents/Resources/resources/runtime"));
        assert!(runtime(Path::new("/tmp/task-relay-desktop")).is_err());
    }
}
