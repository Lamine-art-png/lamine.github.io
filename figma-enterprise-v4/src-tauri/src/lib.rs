use serde::Serialize;
use tauri::{plugin::TauriPlugin, Manager, Runtime};
use url::Url;

const CREDENTIAL_SERVICE: &str = "com.agroai.enterprise";
const ACCESS_TOKEN_ACCOUNT: &str = "access-token";
const MAX_ACCESS_TOKEN_BYTES: usize = 32 * 1024;

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

fn credential_entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(CREDENTIAL_SERVICE, ACCESS_TOKEN_ACCOUNT)
        .map_err(|_| "credential_store_unavailable".to_string())
}

fn is_local_desktop_navigation(url: &Url) -> bool {
    if url.scheme() == "tauri" {
        return true;
    }
    if url.scheme() == "https" && url.host_str() == Some("tauri.localhost") {
        return true;
    }
    if cfg!(debug_assertions)
        && url.scheme() == "http"
        && matches!(url.host_str(), Some("127.0.0.1") | Some("localhost"))
    {
        return true;
    }
    false
}

fn desktop_navigation_guard<R: Runtime>() -> TauriPlugin<R> {
    tauri::plugin::Builder::new("agroai-desktop-navigation-guard")
        .on_navigation(|_webview, url| {
            if is_local_desktop_navigation(url) {
                return true;
            }
            if matches!(url.scheme(), "https" | "http" | "mailto") {
                let _ = webbrowser::open(url.as_str());
            }
            false
        })
        .build()
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
fn desktop_get_access_token() -> Result<Option<String>, String> {
    let entry = credential_entry()?;
    match entry.get_password() {
        Ok(token) if token.is_empty() => Ok(None),
        Ok(token) => Ok(Some(token)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(_) => Err("credential_read_failed".to_string()),
    }
}

#[tauri::command]
fn desktop_set_access_token(token: String) -> Result<(), String> {
    if token.is_empty() || token.len() > MAX_ACCESS_TOKEN_BYTES {
        return Err("invalid_access_token".to_string());
    }
    credential_entry()?
        .set_password(&token)
        .map_err(|_| "credential_write_failed".to_string())
}

#[tauri::command]
fn desktop_delete_access_token() -> Result<(), String> {
    let entry = credential_entry()?;
    match entry.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(_) => Err("credential_delete_failed".to_string()),
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
        .plugin(desktop_navigation_guard())
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            desktop_runtime_info,
            desktop_get_access_token,
            desktop_set_access_token,
            desktop_delete_access_token,
            desktop_open_external
        ])
        .run(tauri::generate_context!())
        .expect("error while running AGRO-AI Enterprise Portal desktop application");
}
