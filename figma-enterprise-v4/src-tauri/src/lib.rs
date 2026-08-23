use serde::Serialize;
use tauri::Manager;
use url::Url;

#[derive(Serialize)]
struct DesktopRuntimeInfo {
    product: &'static str,
    channel: &'static str,
    version: String,
    platform: &'static str,
}

fn desktop_platform() -> &'static str {
    if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else if cfg!(target_os = "linux") {
        "linux"
    } else {
        "unknown"
    }
}

#[tauri::command]
fn desktop_runtime_info(app: tauri::AppHandle) -> DesktopRuntimeInfo {
    DesktopRuntimeInfo {
        product: "AGRO-AI Enterprise Portal",
        channel: "desktop",
        version: app.package_info().version.to_string(),
        platform: desktop_platform(),
    }
}

#[tauri::command]
fn desktop_open_external(url: String) -> Result<(), String> {
    let parsed = Url::parse(&url).map_err(|_| "invalid_url".to_string())?;
    if !matches!(parsed.scheme(), "https" | "http" | "mailto") {
        return Err("unsupported_url_scheme".to_string());
    }
    webbrowser::open(parsed.as_str()).map_err(|_| "open_external_failed".to_string())?;
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        // Keep this first. The deep-link plugin integrates with single-instance
        // on Windows and Linux so an agroai:// URL is delivered to the running app.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![desktop_runtime_info, desktop_open_external])
        .run(tauri::generate_context!())
        .expect("error while running AGRO-AI Enterprise Portal desktop application");
}
