use std::path::PathBuf;

use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager};

// On Windows, Tauri's path().resolve() may return UNC paths (\\?\C:\...).
// Python's pycryptodome fails to load .pyd files when __file__ has UNC prefix.
// Use dunce to convert UNC paths to regular DOS paths.
#[cfg(windows)]
use dunce;

/// Normalize path to regular DOS format on Windows (remove \\?\ prefix)
fn normalize_path(path: PathBuf) -> PathBuf {
    #[cfg(windows)]
    {
        dunce::simplified(&path).to_path_buf()
    }
    #[cfg(not(windows))]
    {
        path
    }
}

pub struct BundledBackendPaths {
    pub python_executable: PathBuf,
    pub server_directory: PathBuf,
    pub runtime_directory: PathBuf,
    pub site_packages_directory: PathBuf,
}

struct ResourceRelativePaths {
    python_executable: &'static str,
    server_directory: &'static str,
    runtime_directory: &'static str,
    site_packages_directory: &'static str,
}

fn resource_relative_paths() -> ResourceRelativePaths {
    ResourceRelativePaths {
        python_executable: "resources/python/python.exe",
        server_directory: "resources/server",
        runtime_directory: "resources/runtime",
        site_packages_directory: "resources/python/Lib/site-packages",
    }
}

#[cfg(test)]
mod tests {
    use super::resource_relative_paths;

    #[test]
    fn resource_paths_match_bundle_resource_layout() {
        let paths = resource_relative_paths();

        assert_eq!(paths.python_executable, "resources/python/python.exe");
        assert_eq!(paths.server_directory, "resources/server");
        assert_eq!(paths.runtime_directory, "resources/runtime");
        assert_eq!(
            paths.site_packages_directory,
            "resources/python/Lib/site-packages"
        );
    }
}

/// In dev mode (tauri dev), use the source `server/` directory directly
/// so backend code changes take effect immediately without copying.
/// In release mode (tauri build), use the bundled resources.
pub fn resolve_paths(app: &AppHandle) -> BundledBackendPaths {
    let relative = resource_relative_paths();

    let python_executable = app
        .path()
        .resolve(relative.python_executable, BaseDirectory::Resource)
        .expect("missing bundled python executable");

    let resource_server = app
        .path()
        .resolve(relative.server_directory, BaseDirectory::Resource)
        .expect("missing bundled server directory");

    let site_packages_directory = app
        .path()
        .resolve(relative.site_packages_directory, BaseDirectory::Resource)
        .expect("missing bundled site-packages directory");

    let runtime_directory = app
        .path()
        .resolve(relative.runtime_directory, BaseDirectory::Resource)
        .expect("missing bundled runtime directory");

    // In dev mode, use source server/ directory directly (no sync needed).
    // In release mode, use the bundled resources/server/.
    //
    // NOTE: BaseDirectory::Resource resolves to target/debug/resources/ in dev mode,
    // NOT src-tauri/resources/ — so parent-counting is fragile.
    // Use CARGO_MANIFEST_DIR (= src-tauri/) instead for a reliable path to the project root.
    let (server_directory, python_executable, site_packages_directory) = if cfg!(debug_assertions) {
        let src_tauri_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let project_root = src_tauri_dir.parent().expect("src-tauri should have a parent");
        let source_server = project_root.join("server");

        // Prefer NOWORK_PYTHON env var, then auto-detect from CONDA_PREFIX.
        // Falls back to bundled resources/python if neither is set.
        let dev_python = std::env::var("NOWORK_PYTHON")
            .ok()
            .map(|p| PathBuf::from(p).join("python.exe"))
            .filter(|p| p.exists())
            .or_else(|| {
                std::env::var("CONDA_PREFIX")
                    .ok()
                    .map(|p| PathBuf::from(p).join("python.exe"))
                    .filter(|p| p.exists())
            });

        let (py, sp) = if let Some(python) = dev_python {
            let site_pkgs = python.parent().unwrap().join("Lib").join("site-packages");
            (python, site_pkgs)
        } else if source_server.join("app").exists() {
            (python_executable, site_packages_directory)
        } else {
            (python_executable, site_packages_directory)
        };

        let srv = if source_server.join("app").exists() {
            source_server
        } else {
            resource_server
        };

        (srv, py, sp)
    } else {
        (resource_server, python_executable, site_packages_directory)
    };

    BundledBackendPaths {
        python_executable: normalize_path(python_executable),
        server_directory: normalize_path(server_directory),
        runtime_directory: normalize_path(runtime_directory),
        site_packages_directory: normalize_path(site_packages_directory),
    }
}
