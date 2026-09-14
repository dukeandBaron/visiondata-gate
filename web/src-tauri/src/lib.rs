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

#[derive(Serialize)]
struct DesktopStartupReceipt {
    schema_version: &'static str,
    status: &'static str,
    gateway: &'static str,
    gateway_port: u16,
    fastapi_port: u16,
    bind_scope: &'static str,
    hmac_readiness_verified: bool,
    production_release_allowed: bool,
    machine_write_permitted: bool,
}

struct DesktopState {
    runtime: DesktopRuntimeConfig,
    gateway_port: u16,
    fastapi_child: Mutex<Option<Child>>,
    gateway_child: Mutex<Option<Child>>,
}

fn required_windows_dir(name: &str) -> Result<PathBuf, String> {
    env::var_os(name)
        .map(PathBuf::from)
        .ok_or_else(|| format!("{name} is unavailable"))
}

fn windows_process_path(path: PathBuf) -> PathBuf {
    let value = path.to_string_lossy();
    if let Some(stripped) = value.strip_prefix("\\\\?\\UNC\\") {
        return PathBuf::from(format!("\\\\{stripped}"));
    }
    if let Some(stripped) = value.strip_prefix("\\\\?\\") {
        return PathBuf::from(stripped);
    }
    path
}

fn reserve_loopback_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("failed to reserve a loopback port: {error}"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("failed to read the loopback port: {error}"))
}

fn reserve_service_ports() -> Result<(u16, u16), String> {
    let fastapi_port = reserve_loopback_port()?;
    for _ in 0..8 {
        let gateway_port = reserve_loopback_port()?;
        if gateway_port != fastapi_port {
            return Ok((fastapi_port, gateway_port));
        }
    }
    Err("failed to reserve distinct local service ports".to_string())
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

    #[cfg(debug_assertions)]
    {
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
    }
    Err("the packaged FastAPI sidecar is missing".to_string())
}

fn gateway_jar(app: &tauri::App) -> Result<PathBuf, String> {
    let bundled = app
        .path()
        .resource_dir()
        .map_err(|error| format!("failed to resolve the resource directory: {error}"))?
        .join("gateway")
        .join("visiondata-gate-gateway.jar");
    if bundled.is_file() {
        return Ok(bundled);
    }
    #[cfg(debug_assertions)]
    {
        let development = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("gateway")
            .join("target")
            .join("visiondata-gate-gateway.jar");
        if development.is_file() {
            return development.canonicalize().map_err(|error| {
                format!("failed to resolve the development gateway JAR: {error}")
            });
        }
    }
    Err("the packaged Spring Boot gateway JAR is missing".to_string())
}

fn gateway_java(app: &tauri::App) -> Result<PathBuf, String> {
    let bundled = app
        .path()
        .resource_dir()
        .map_err(|error| format!("failed to resolve the resource directory: {error}"))?
        .join("gateway")
        .join("runtime")
        .join("bin")
        .join("java.exe");
    if bundled.is_file() {
        return Ok(bundled);
    }
    #[cfg(debug_assertions)]
    {
        let development = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("gateway")
            .join("runtime")
            .join("bin")
            .join("java.exe");
        if development.is_file() {
            return development.canonicalize().map_err(|error| {
                format!("failed to resolve the development Java runtime: {error}")
            });
        }
    }
    Err("the packaged Java runtime is missing".to_string())
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

fn start_gateway(
    app: &tauri::App,
    gateway_port: u16,
    fastapi_port: u16,
    log_file: &Path,
) -> Result<Child, String> {
    let java = windows_process_path(gateway_java(app)?);
    let jar = windows_process_path(gateway_jar(app)?);
    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_file)
        .map_err(|error| format!("failed to open the gateway log: {error}"))?;
    let stderr = stdout
        .try_clone()
        .map_err(|error| format!("failed to clone the gateway log handle: {error}"))?;

    Command::new(java)
        .arg("-Dfile.encoding=UTF-8")
        .arg("-jar")
        .arg(jar)
        .env("VISIONDATA_GATEWAY_PORT", gateway_port.to_string())
        .env(
            "VISIONDATA_FASTAPI_BASE_URL",
            format!("http://127.0.0.1:{fastapi_port}"),
        )
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .map_err(|error| format!("failed to start the Spring Boot gateway: {error}"))
}

fn write_startup_receipt(
    log_root: &Path,
    gateway_port: u16,
    fastapi_port: u16,
) -> Result<(), String> {
    let receipt = DesktopStartupReceipt {
        schema_version: "visiondata-gate.desktop-startup.v1",
        status: "READY",
        gateway: "SPRING_BOOT_WEBFLUX",
        gateway_port,
        fastapi_port,
        bind_scope: "LOOPBACK_ONLY",
        hmac_readiness_verified: true,
        production_release_allowed: false,
        machine_write_permitted: false,
    };
    let mut serialized = serde_json::to_vec_pretty(&receipt)
        .map_err(|error| format!("failed to serialize the startup receipt: {error}"))?;
    serialized.push(b'\n');
    fs::write(log_root.join("desktop-startup.json"), serialized)
        .map_err(|error| format!("failed to write the startup receipt: {error}"))
}

fn schedule_smoke_exit(app: &tauri::App) {
    let Ok(raw_delay) = env::var("VISIONDATA_DESKTOP_SMOKE_EXIT_AFTER_READY_MS") else {
        return;
    };
    let Ok(delay_ms) = raw_delay.parse::<u64>() else {
        return;
    };
    if !(250..=10_000).contains(&delay_ms) {
        return;
    }
    let app_handle = app.handle().clone();
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(delay_ms));
        app_handle.exit(0);
    });
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

fn stop_child(slot: &Mutex<Option<Child>>, grace: Duration) {
    let Ok(mut guard) = slot.lock() else {
        return;
    };
    let Some(mut child) = guard.take() else {
        return;
    };

    let deadline = Instant::now() + grace;
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

fn stop_services(state: &DesktopState) {
    request_graceful_shutdown(state.gateway_port, &state.runtime.session_token);
    stop_child(&state.fastapi_child, Duration::from_secs(4));
    stop_child(&state.gateway_child, Duration::from_secs(1));
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

            let (fastapi_port, gateway_port) = reserve_service_ports()?;
            let token = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
            let startup_secret = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
            let fastapi_log_file = log_root.join("fastapi.log");
            let gateway_log_file = log_root.join("gateway.log");
            let sample_data_root = resource_dir.join("sample_data");
            let runtime = DesktopRuntimeConfig {
                api_base_url: format!("http://127.0.0.1:{gateway_port}"),
                session_token: token.clone(),
                data_root: product_root.to_string_lossy().into_owned(),
                config_file: config_file.to_string_lossy().into_owned(),
                sample_data_root: sample_data_root.to_string_lossy().into_owned(),
            };
            let mut fastapi_child = start_backend(
                app,
                fastapi_port,
                &token,
                &startup_secret,
                &product_root,
                &config_file,
                &fastapi_log_file,
            )?;
            let mut gateway_child =
                match start_gateway(app, gateway_port, fastapi_port, &gateway_log_file) {
                    Ok(child) => child,
                    Err(error) => {
                        let _ = fastapi_child.kill();
                        let _ = fastapi_child.wait();
                        return Err(error.into());
                    }
                };
            if let Err(error) = wait_for_backend(&mut gateway_child, gateway_port, &startup_secret)
            {
                let _ = gateway_child.kill();
                let _ = gateway_child.wait();
                let _ = fastapi_child.kill();
                let _ = fastapi_child.wait();
                return Err(error.into());
            }
            if let Err(error) = write_startup_receipt(&log_root, gateway_port, fastapi_port) {
                let _ = gateway_child.kill();
                let _ = gateway_child.wait();
                let _ = fastapi_child.kill();
                let _ = fastapi_child.wait();
                return Err(error.into());
            }
            app.manage(DesktopState {
                runtime,
                gateway_port,
                fastapi_child: Mutex::new(Some(fastapi_child)),
                gateway_child: Mutex::new(Some(gateway_child)),
            });
            schedule_smoke_exit(app);
            Ok(())
        });

    builder
        .build(tauri::generate_context!())
        .expect("failed to build the VisionData Gate desktop application")
        .run(|app_handle, event| {
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                if let Some(state) = app_handle.try_state::<DesktopState>() {
                    stop_services(&state);
                }
            }
        });
}
