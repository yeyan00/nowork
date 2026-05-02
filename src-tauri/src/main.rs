#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend_paths;
mod backend_process;

use std::process::Child;
use std::sync::{Arc, Mutex};

use rfd::FileDialog;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager, RunEvent, WindowEvent,
};

#[tauri::command]
fn open_attachment_dialog(kind: String, multiple: bool) -> Result<Vec<String>, String> {
    let mut dialog = FileDialog::new();
    dialog = match kind.as_str() {
        "image" => dialog.add_filter("Images", &["png", "jpg", "jpeg", "webp", "gif", "bmp"]),
        "video" => dialog.add_filter("Videos", &["mp4", "mov", "mkv", "avi", "webm", "m4v"]),
        _ => dialog,
    };

    let files = if multiple {
        dialog.pick_files().unwrap_or_default()
    } else {
        dialog.pick_file().map(|file| vec![file]).unwrap_or_default()
    };

    Ok(files
        .into_iter()
        .map(|path| path.to_string_lossy().to_string())
        .collect())
}

/// Open an external URL in the system's default browser.
/// In Tauri's WebView2, `window.open()` is typically blocked;
/// this command uses the OS to open the link instead.
#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/C", "start", &url])
            .spawn()
            .map_err(|e| format!("Failed to open URL: {e}"))?;
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Failed to open URL: {e}"))?;
    }
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Failed to open URL: {e}"))?;
    }
    Ok(())
}

/// Read the runtime config file written by the Python backend.
/// In release mode, the backend writes to resources/runtime/app-runtime.json,
/// which is not accessible via fetch() from the embedded webview.
/// The frontend calls this Tauri command to discover the backend URL.
#[tauri::command]
fn get_runtime_config(app: AppHandle) -> Result<String, String> {
    use tauri::path::BaseDirectory;

    let runtime_path = app
        .path()
        .resolve("resources/runtime/app-runtime.json", BaseDirectory::Resource)
        .map_err(|e| format!("Failed to resolve runtime path: {e}"))?;

    std::fs::read_to_string(&runtime_path)
        .map_err(|e| format!("Failed to read runtime config: {e}"))
}

/// Read backend error logs for diagnostics.
/// The frontend calls this when health check fails to show the user what went wrong.
#[tauri::command]
fn get_backend_error(app: AppHandle) -> Result<String, String> {
    use tauri::path::BaseDirectory;

    let logs_dir = app
        .path()
        .resolve("resources/runtime/logs", BaseDirectory::Resource)
        .map_err(|e| format!("Failed to resolve logs path: {e}"))?;

    let mut parts: Vec<String> = Vec::new();

    // Read stderr log (most useful for startup errors)
    let stderr_path = logs_dir.join("backend-err.log");
    if stderr_path.exists() {
        match std::fs::read_to_string(&stderr_path) {
            Ok(content) if !content.is_empty() => {
                parts.push(format!("--- stderr (backend-err.log) ---\n{content}"));
            }
            _ => {}
        }
    }

    // Read stdout log as fallback
    let stdout_path = logs_dir.join("backend.log");
    if stdout_path.exists() {
        match std::fs::read_to_string(&stdout_path) {
            Ok(content) if !content.is_empty() => {
                parts.push(format!("--- stdout (backend.log) ---\n{content}"));
            }
            _ => {}
        }
    }

    if parts.is_empty() {
        Ok("(no backend logs found)".to_string())
    } else {
        Ok(parts.join("\n\n"))
    }
}

fn main() {
    let backend_child: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
    let child_for_setup = Arc::clone(&backend_child);
    let child_for_exit = Arc::clone(&backend_child);

    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![open_attachment_dialog, get_runtime_config, get_backend_error, open_external_url])
        .setup(move |app| {
            let paths = backend_paths::resolve_paths(&app.handle());
            let child =
                backend_process::start_backend(&paths).expect("failed to start bundled backend");

            *child_for_setup
                .lock()
                .expect("failed to store backend child") = Some(child);

            // Wait for the backend to write app-runtime.json.
            // The Python process needs a few seconds to initialize, choose a port,
            // and write the runtime config file. We block here so the frontend
            // doesn't show "service not ready" on first launch.
            let runtime_file = paths.runtime_directory.join("app-runtime.json");
            eprintln!("[nowork] Waiting for runtime config: {}", runtime_file.display());
            let mut waited_ms: u64 = 0;
            loop {
                if runtime_file.exists() {
                    eprintln!("[nowork] Runtime config appeared after {}ms", waited_ms);
                    break;
                }
                if waited_ms >= 30_000 {
                    eprintln!("[nowork] WARNING: Runtime config not found after 30s, proceeding anyway");
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(200));
                waited_ms += 200;
            }

            // Setup system tray with menu
            // Determine menu text based on system locale
            let locale = sys_locale::get_locale().unwrap_or_else(|| "en".to_string());
            let is_chinese = locale.starts_with("zh");
            let (show_text, quit_text) = if is_chinese {
                ("打开", "退出")
            } else {
                ("Show", "Quit")
            };

            let show_item = MenuItem::with_id(app, "show", show_text, true, None::<&str>)
                .expect("failed to create show menu item");
            let quit_item = MenuItem::with_id(app, "quit", quit_text, true, None::<&str>)
                .expect("failed to create quit menu item");
            let menu = Menu::with_items(app, &[&show_item, &quit_item])
                .expect("failed to create tray menu");

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)
                .expect("failed to build tray icon");

            // Intercept window close request → hide to tray instead of exit
            if let Some(window) = app.get_webview_window("main") {
                let window_clone = window.clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        let _ = window_clone.hide();
                    }
                });
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(move |_app_handle, event| match event {
            RunEvent::Exit => {
                let mut guard = child_for_exit.lock().expect("failed to lock backend child");
                if let Some(child) = guard.as_mut() {
                    backend_process::stop_backend(child);
                }
                *guard = None;
            }
            _ => {}
        });
}
