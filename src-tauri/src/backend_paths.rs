use std::path::PathBuf;

use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager};

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
        site_packages_directory: "resources/server/site-packages",
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
            "resources/server/site-packages"
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
    let server_directory = if cfg!(debug_assertions) {
        let src_tauri_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let project_root = src_tauri_dir.parent().expect("src-tauri should have a parent");
        let source_server = project_root.join("server");
        if source_server.join("app").exists() {
            source_server
        } else {
            resource_server
        }
    } else {
        resource_server
    };

    BundledBackendPaths {
        python_executable,
        server_directory,
        runtime_directory,
        site_packages_directory,
    }
}
