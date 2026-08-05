fn main() {
    match drive_update::run_watchdog_from_args() {
        Ok(true) => {}
        Ok(false) => drive_desktop_lib::run(),
        Err(error) => {
            eprintln!("desktop update watchdog failed: {error}");
            std::process::exit(1);
        }
    }
}
