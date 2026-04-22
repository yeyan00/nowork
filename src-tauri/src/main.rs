#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend_paths;
mod backend_process;

use std::process::Child;
use std::sync::{Arc, Mutex};

use rfd::FileDialog;
use tauri::{AppHandle, Manager, RunEvent};

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

fn main() {
    let backend_child: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
    let child_for_setup = Arc::clone(&backend_child);
    let child_for_exit = Arc::clone(&backend_child);

    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![open_attachment_dialog, get_runtime_config])
        .setup(move |app| {
            let paths = backend_paths::resolve_paths(&app.handle());
            let child =
                backend_process::start_backend(&paths).expect("failed to start bundled backend");

            *child_for_setup
                .lock()
                .expect("failed to store backend child") = Some(child);

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(move |_app_handle, event| {
            if let RunEvent::Exit = event {
                let mut guard = child_for_exit.lock().expect("failed to lock backend child");
                if let Some(child) = guard.as_mut() {
                    backend_process::stop_backend(child);
                }
                *guard = None;
            }
        });
}
