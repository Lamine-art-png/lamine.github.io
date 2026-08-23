use serde::Serialize;
use tauri::{Manager, Runtime};
use tauri_plugin_deep_link::DeepLinkExt;
use url::Url;

const DESKTOP_DEEP_LINK_EVENT: &str = "agroai:desktop-deep-link";

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

fn validated_deep_link(raw: &str) -> Option<String> {
    let parsed = Url::parse(raw).ok()?;
    if parsed.scheme() != "agroai" {
        return None;
    }
    Some(parsed.to_string())
}

fn dispatch_deep_link<R: Runtime>(app: &tauri::AppHandle<R>, raw: &str) {
    let Some(url) = validated_deep_link(raw) else {
        return;
    };
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let encoded = match serde_json::to_string(&url) {
        Ok(value) => value,
        Err(_) => return,
    };
    let script = format!(
        "window.dispatchEvent(new CustomEvent('{DESKTOP_DEEP_LINK_EVENT}', {{ detail: {{ url: {encoded} }} }}));"
    );
    let _ = window.eval(&script);
    let _ = window.show();
    let _ = window.set_focus();
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
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
            for argument in argv {
                if argument.starts_with("agroai://") {
                    dispatch_deep_link(app, &argument);
                    break;
                }
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![desktop_runtime_info, desktop_open_external])
        .setup(|app| {
            let handle = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                for url in event.urls() {
                    dispatch_deep_link(&handle, url.as_str());
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running AGRO-AI Enterprise Portal desktop application");
}
