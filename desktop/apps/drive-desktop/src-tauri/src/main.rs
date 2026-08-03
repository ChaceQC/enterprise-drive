fn main() {
    if drive_update::run_watchdog_from_args().unwrap_or(false) {
        return;
    }
    drive_desktop_lib::run();
}
