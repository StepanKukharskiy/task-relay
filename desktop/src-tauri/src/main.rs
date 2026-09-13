#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(target_os = "macos")]
mod messages_service;

fn main() {
    #[cfg(target_os = "macos")]
    if std::env::args().skip(1).eq(["--messages-service"]) {
        match messages_service::run() {
            Ok(code) => std::process::exit(code),
            Err(error) => { eprintln!("{error}"); std::process::exit(1); }
        }
    }
    task_relay_desktop_lib::run();
}
