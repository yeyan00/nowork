use std::env;
use std::fs::File;
use std::process::{Child, Command, Stdio};

use crate::backend_paths::BundledBackendPaths;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

// ── Windows Job Object ──────────────────────────────────────────────
// Place the child process in a Job with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
// When the parent process exits (even via Ctrl+C, crash, or task kill),
// the OS automatically terminates all processes in the Job.

#[cfg(windows)]
mod win_job {
    use std::mem;
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;

    // Minimal raw FFI — avoids windows-sys feature flag complexity
    type HANDLE = *mut std::ffi::c_void;
    type BOOL = i32;
    type DWORD = u32;

    const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: DWORD = 9;
    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: DWORD = 0x2000;

    #[repr(C)]
    struct IO_COUNTERS {
        ReadOperationCount: u64,
        WriteOperationCount: u64,
        OtherOperationCount: u64,
        ReadTransferCount: u64,
        WriteTransferCount: u64,
        OtherTransferCount: u64,
    }

    #[repr(C)]
    struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        PerProcessUserTimeLimit: i64,
        PerJobUserTimeLimit: i64,
        LimitFlags: DWORD,
        MinimumWorkingSetSize: usize,
        MaximumWorkingSetSize: usize,
        ActiveProcessLimit: DWORD,
        Affinity: usize,
        PriorityClass: DWORD,
        SchedulingClass: DWORD,
    }

    #[repr(C)]
    struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        BasicLimitInformation: JOBOBJECT_BASIC_LIMIT_INFORMATION,
        IoInfo: IO_COUNTERS,
        ProcessMemoryLimit: usize,
        JobMemoryLimit: usize,
        PeakProcessMemoryUsed: usize,
        PeakJobMemoryUsed: usize,
    }

    extern "system" {
        fn CreateJobObjectW(
            lpJobAttributes: *mut std::ffi::c_void,
            lpName: *const u16,
        ) -> HANDLE;
        fn SetInformationJobObject(
            hJob: HANDLE,
            JobObjectInformationClass: DWORD,
            lpJobObjectInformation: *const std::ffi::c_void,
            cbJobObjectInformationLength: DWORD,
        ) -> BOOL;
        fn AssignProcessToJobObject(hJob: HANDLE, hProcess: HANDLE) -> BOOL;
    }

    /// Create a Job Object that kills all child processes when the handle is closed.
    fn create_kill_on_close_job() -> Option<HANDLE> {
        unsafe {
            let job = CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
            if job.is_null() {
                return None;
            }

            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

            let result = SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                &info as *const _ as *const std::ffi::c_void,
                mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as DWORD,
            );

            if result == 0 {
                return None;
            }

            Some(job)
        }
    }

    /// Assign a child process to the kill-on-close Job.
    pub fn assign_to_job(child: &Child) -> bool {
        unsafe {
            let job = match create_kill_on_close_job() {
                Some(h) => h,
                None => return false,
            };

            let handle = child.as_raw_handle() as HANDLE;
            AssignProcessToJobObject(job, handle) != 0
        }
    }
}

#[cfg(windows)]
fn windows_creation_flags() -> u32 {
    CREATE_NO_WINDOW
}

#[cfg(test)]
mod tests {
    #[cfg(windows)]
    #[test]
    fn windows_backend_process_uses_create_no_window_flag() {
        assert_eq!(super::windows_creation_flags(), 0x08000000);
    }
}

pub fn start_backend(paths: &BundledBackendPaths) -> std::io::Result<Child> {
    let python_path = env::join_paths([
        paths.server_directory.as_path(),
        paths.site_packages_directory.as_path(),
    ])
    .expect("failed to join python search paths");

    // Resolve web runtime path: <project_root>/web/public/runtime/app-runtime.json
    // In dev mode: server_directory = <project>/server → parent = <project>
    // In release mode: server_directory = <app>/resources/server → no web dir (skip)
    let web_runtime = paths.server_directory.parent()
        .map(|project_root| {
            project_root.join("web").join("public").join("runtime").join("app-runtime.json")
        });

    // Log resolved paths for debugging
    eprintln!("[nowork] Backend paths:");
    eprintln!("[nowork]   python:   {}", paths.python_executable.display());
    eprintln!("[nowork]   server:   {}", paths.server_directory.display());
    eprintln!("[nowork]   runtime:  {}", paths.runtime_directory.display());
    eprintln!("[nowork]   site-pkgs: {}", paths.site_packages_directory.display());
    eprintln!("[nowork]   PYTHONPATH: {}", python_path.to_string_lossy());
    if let Some(ref web_rt) = web_runtime {
        eprintln!("[nowork]   web-rt:   {}", web_rt.display());
    }

    let mut command = Command::new(&paths.python_executable);

    command
        .args(["-m", "app.run"])
        .current_dir(&paths.server_directory)
        .env("PYTHONPATH", python_path)
        .env("NOWORK_RUNTIME_DIR", &paths.runtime_directory);

    // Write runtime file to web/public so Vite dev server can find it
    if let Some(ref web_rt) = web_runtime {
        if web_rt.parent().map_or(false, |p| p.parent().map_or(false, |pp| pp.exists())) {
            command.env("NOWORK_WEB_RUNTIME_FILE", web_rt);
        }
    }

    // In dev mode, show backend output in terminal for debugging.
    // In release mode, redirect to log files so startup errors can be diagnosed.
    if cfg!(debug_assertions) {
        command.stdout(Stdio::inherit()).stderr(Stdio::inherit());
    } else {
        // Ensure runtime/logs directory exists
        let logs_dir = paths.runtime_directory.join("logs");
        if let Err(e) = std::fs::create_dir_all(&logs_dir) {
            eprintln!("[nowork] Warning: failed to create logs dir {}: {e}", logs_dir.display());
        }

        let stdout_path = logs_dir.join("backend.log");
        let stderr_path = logs_dir.join("backend-err.log");

        match File::create(&stdout_path) {
            Ok(f) => { command.stdout(f); }
            Err(e) => {
                eprintln!("[nowork] Warning: failed to create {}: {e}", stdout_path.display());
                command.stdout(Stdio::null());
            }
        }
        match File::create(&stderr_path) {
            Ok(f) => { command.stderr(f); }
            Err(e) => {
                eprintln!("[nowork] Warning: failed to create {}: {e}", stderr_path.display());
                command.stderr(Stdio::null());
            }
        }
    }

    #[cfg(windows)]
    command.creation_flags(windows_creation_flags());

    let child = command.spawn()?;

    // On Windows, assign child to a Job Object so it is automatically killed
    // when the parent exits (Ctrl+C, crash, task kill, etc.)
    #[cfg(windows)]
    {
        if !win_job::assign_to_job(&child) {
            eprintln!("[nowork] Warning: failed to assign backend to Job Object — \
                       child process may survive parent exit");
        }
    }

    Ok(child)
}

pub fn stop_backend(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}
