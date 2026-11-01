from modules.desktop_dependencies import docker_desktop_path, ensure_docker


def test_per_user_installation_is_found(tmp_path):
    local = tmp_path / 'user'
    exe = local / 'Programs/DockerDesktop/Docker Desktop.exe'
    exe.parent.mkdir(parents=True)
    exe.touch()
    assert docker_desktop_path({'LOCALAPPDATA': str(local),
                                'ProgramFiles': str(tmp_path / 'system')}) == exe


def test_existing_daemon_is_reused_without_launch():
    def forbidden(path):
        raise AssertionError('Must not launch another desktop')
    assert ensure_docker(cli='docker', ready=lambda: True, launch=forbidden) == {
        'ready': True, 'started': False}


def test_startup_waits_for_daemon_without_rebuilding():
    replies = iter([False, False, True])
    launched = []
    result = ensure_docker(cli='docker', desktop='installed.exe',
        ready=lambda: next(replies), launch=launched.append,
        clock=lambda: 0, sleep=lambda seconds: None)
    assert result == {'ready': True, 'started': True}
    assert launched == ['installed.exe']


def test_failed_startup_has_bounded_wait():
    tick = [0]
    def advance(seconds):
        tick[0] += seconds
    result = ensure_docker(cli='docker', desktop='installed.exe', ready=lambda: False,
        launch=lambda path: None, clock=lambda: tick[0], sleep=advance, wait_seconds=2)
    assert not result['ready'] and result['started'] and tick[0] == 2
