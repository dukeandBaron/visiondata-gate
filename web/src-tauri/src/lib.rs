#[cfg(not(target_os = "windows"))]
compile_error!("VisionData Gate desktop packaging is Windows-only.");

use serde::Serialize;
use sha2::{Digest, Sha256};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{Manager, RunEvent};
use uuid::Uuid;

const CREATE_NO_WINDOW: u32 = 0x08000000;
const SHA256_BLOCK_BYTES: usize = 64;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopRuntimeConfig {
    api_base_url: String,
    session_token: String,
    data_root: String,
    config_file: String,
    sample_data_root: String,
}

struct DesktopState {
    runtime: DesktopRuntimeConfig,
    port: u16,
    child: Mutex<Option<Child>>,
}

fn required_windows_dir(name: &str) -> Result<PathBuf, String> {
    env::var_os(name)
        .map(PathBuf::from)
        .ok_or_else(|| format!("{name} is unavailable"))
}

fn reserve_loopback_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("failed to reserve a loopback port: {error}"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("failed to read the loopback port: {error}"))
}

fn backend_executable(app: &tauri::App) -> Result<PathBuf, String> {
    let bundled = app
        .path()
        .resource_dir()
        .map_err(|error| format!("failed to resolve the resource directory: {error}"))?
        .join("backend")
        .join("visiondata-gate-backend.exe");
    if bundled.is_file() {
        return Ok(bundled);
    }

    let development = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("desktop")
        .join("dist")
        .join("visiondata-gate-backend")
        .join("visiondata-gate-backend.exe");
    if development.is_file() {
        return development
            .canonicalize()
            .map_err(|error| format!("failed to resolve the development sidecar: {error}"));
    }
    Err("the packaged FastAPI sidecar is missing".to_string())
}

fn expected_startup_proof(secret: &str, challenge: &str) -> String {
    let mut key_block = [0_u8; SHA256_BLOCK_BYTES];
    let secret_bytes = secret.as_bytes();
    if secret_bytes.len() > SHA256_BLOCK_BYTES {
        let digest = Sha256::digest(secret_bytes);
        key_block[..digest.len()].copy_from_slice(&digest);
    } else {
        key_block[..secret_bytes.len()].copy_from_slice(secret_bytes);
    }
    let mut inner_pad = [0x36_u8; SHA256_BLOCK_BYTES];
    let mut outer_pad = [0x5c_u8; SHA256_BLOCK_BYTES];
    for index in 0..SHA256_BLOCK_BYTES {
        inner_pad[index] ^= key_block[index];
        outer_pad[index] ^= key_block[index];
    }
    let mut inner = Sha256::new();
    inner.update(inner_pad);
    inner.update(challenge.as_bytes());
    let inner_digest = inner.finalize();
    let mut outer = Sha256::new();
    outer.update(outer_pad);
    outer.update(inner_digest);
    outer
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn probe_backend_identity(port: u16, challenge: &str) -> Result<String, String> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(150))
        .map_err(|error| format!("desktop backend is not accepting connections: {error}"))?;
    stream
        .set_read_timeout(Some(Duration::from_millis(350)))
        .map_err(|error| format!("failed to bound the readiness read: {error}"))?;
    stream
        .set_write_timeout(Some(Duration::from_millis(350)))
        .map_err(|error| format!("failed to bound the readiness write: {error}"))?;
    let request = format!(
        "GET /v1/desktop/readiness?challenge={challenge} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| format!("failed to request the readiness proof: {error}"))?;
    stream
        .flush()
        .map_err(|error| format!("failed to flush the readiness request: {error}"))?;
    let mut response = String::new();
    stream
        .take(8192)
        .read_to_string(&mut response)
        .map_err(|error| format!("failed to read the readiness proof: {error}"))?;
    let (headers, body) = response
        .split_once("\r\n\r\n")
        .ok_or_else(|| "desktop readiness response was malformed".to_string())?;
    if !(headers.starts_with("HTTP/1.1 200 ") || headers.starts_with("HTTP/1.0 200 ")) {
        return Err("desktop readiness response was not successful".to_string());
    }
    Ok(body.trim().to_string())
}

fn wait_for_backend(child: &mut Child, port: u16, startup_secret: &str) -> Result<(), String> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let challenge = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
    let expected_proof = expected_startup_proof(startup_secret, &challenge);
    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        if let Some(status) = child
            .try_wait()
            .map_err(|error| format!("failed to inspect the desktop sidecar: {error}"))?
        {
            return Err(format!("desktop sidecar exited during startup: {status}"));
        }
        if TcpStream::connect_timeout(&address, Duration::from_millis(75)).is_ok() {
            if let Ok(observed_proof) = probe_backend_identity(port, &challenge) {
                if observed_proof == expected_proof {
                    return Ok(());
                }
            }
        }
        thread::sleep(Duration::from_millis(150));
    }
    let _ = child.kill();
    let _ = child.wait();
    Err("desktop sidecar did not become ready within 20 seconds".to_string())
}

fn copy_initial_config_template(resource_dir: &Path, config_file: &Path) -> Result<(), String> {
    if config_file.exists() {
        return Ok(());
    }
    let source = resource_dir.join("config").join(".env.example");
    if !source.is_file() {
        return Err("desktop configuration template is missing".to_string());
    }
    fs::copy(&source, config_file)
        .map(|_| ())
        .map_err(|error| format!("failed to create the initial desktop configuration: {error}"))
}

fn start_backend(
    app: &tauri::App,
    port: u16,
    token: &str,
    startup_secret: &str,
    product_root: &Path,
    config_file: &Path,
    log_file: &Path,
) -> Result<Child, String> {
    let executable = backend_executable(app)?;
    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_file)
        .map_err(|error| format!("failed to open the desktop backend log: {error}"))?;
    let stderr = stdout
        .try_clone()
        .map_err(|error| format!("failed to clone the desktop backend log handle: {error}"))?;

    let mut command = Command::new(executable);
    command
        .arg("--port")
        .arg(port.to_string())
        .env("VISIONDATA_DESKTOP_SESSION_TOKEN", token)
        .env("VISIONDATA_DESKTOP_STARTUP_SECRET", startup_secret)
        .env("VISIONDATA_PRODUCT_ROOT", product_root)
        .env("VISIONDATA_DESKTOP_CONFIG_FILE", config_file)
        .env("VISIONDATA_DESKTOP_LOG_FILE", log_file)
        .env(
            "VISIONDATA_WEB_ORIGINS",
            "http://tauri.localhost,https://tauri.localhost,tauri://localhost",
        )
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .creation_flags(CREATE_NO_WINDOW);

    let mut child = command
        .spawn()
        .map_err(|error| format!("failed to start the desktop sidecar: {error}"))?;
    wait_for_backend(&mut child, port, startup_secret)?;
    Ok(child)
}

fn request_graceful_shutdown(port: u16, token: &str) {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(350)) else {
        return;
    };
    let request = format!(
        "POST /v1/desktop/shutdown HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-VisionData-Desktop-Token: {token}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    );
    let _ = stream.write_all(request.as_bytes());
    let _ = stream.flush();
}

fn stop_backend(state: &DesktopState) {
    let Ok(mut guard) = state.child.lock() else {
        return;
    };
    let Some(mut child) = guard.take() else {
        return;
    };

    request_graceful_shutdown(state.port, &state.runtime.session_token);
    let deadline = Instant::now() + Duration::from_secs(4);
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => return,
            Ok(None) => thread::sleep(Duration::from_millis(100)),
            Err(_) => break,
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[tauri::command]
fn desktop_runtime_config(state: tauri::State<'_, DesktopState>) -> DesktopRuntimeConfig {
    state.runtime.clone()
}

#[tauri::command]
fn open_desktop_config_directory(state: tauri::State<'_, DesktopState>) -> Result<(), String> {
    let directory = PathBuf::from(&state.runtime.config_file)
        .parent()
        .ok_or_else(|| "desktop configuration directory is invalid".to_string())?
        .to_path_buf();
    Command::new("explorer.exe")
        .arg(directory)
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("failed to open the desktop configuration directory: {error}"))
}

pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .invoke_handler(tauri::generate_handler![
            desktop_runtime_config,
            open_desktop_config_directory
        ])
        .setup(|app| {
            let resource_dir = app.path().resource_dir()?;
            let local_root = required_windows_dir("LOCALAPPDATA")?.join("VisionData Gate");
            let product_root = local_root.join("product");
            let log_root = local_root.join("logs");
            let config_root = required_windows_dir("APPDATA")?.join("VisionData Gate");
            let config_file = config_root.join(".env.local");
            fs::create_dir_all(&product_root)?;
            fs::create_dir_all(&log_root)?;
            fs::create_dir_all(&config_root)?;
            copy_initial_config_template(&resource_dir, &config_file)?;

            let port = reserve_loopback_port()?;
            let token = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
            let startup_secret = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
            let log_file = log_root.join("backend.log");
            let sample_data_root = resource_dir.join("sample_data");
            let runtime = DesktopRuntimeConfig {
                api_base_url: format!("http://127.0.0.1:{port}"),
                session_token: token.clone(),
                data_root: product_root.to_string_lossy().into_owned(),
                config_file: config_file.to_string_lossy().into_owned(),
                sample_data_root: sample_data_root.to_string_lossy().into_owned(),
            };
            let child = start_backend(
                app,
                port,
                &token,
                &startup_secret,
                &product_root,
                &config_file,
                &log_file,
            )?;
            app.manage(DesktopState {
                runtime,
                port,
                child: Mutex::new(Some(child)),
            });
            Ok(())
        });

    builder
        .build(tauri::generate_context!())
        .expect("failed to build the VisionData Gate desktop application")
        .run(|app_handle, event| {
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                if let Some(state) = app_handle.try_state::<DesktopState>() {
                    stop_backend(&state);
                }
            }
        });
}
