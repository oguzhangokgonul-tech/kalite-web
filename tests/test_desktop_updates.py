def test_desktop_updates_are_public_and_no_store(client, app, tmp_path):
    app.config["DESKTOP_UPDATE_DIR"] = str(tmp_path)
    (tmp_path / "latest.json").write_text('{"version":"0.1.5"}', encoding="utf-8")
    name = "VolkaPortal-Setup-0.1.5-win-x64.exe"
    (tmp_path / name).write_bytes(b"test-installer")

    manifest = client.get("/desktop-updates/latest.json")
    assert manifest.status_code == 200
    assert manifest.mimetype == "application/json"
    assert "no-store" in manifest.headers["Cache-Control"]
    assert "Set-Cookie" not in manifest.headers

    installer = client.get(f"/desktop-updates/{name}")
    assert installer.status_code == 200
    assert installer.data == b"test-installer"
    assert installer.headers["Content-Disposition"].startswith("attachment;")
    assert client.get("/desktop-updates/other.exe").status_code == 404
    assert client.get("/desktop-updates/%2e%2e%2fsecret.exe").status_code == 404


def test_desktop_updates_missing_release_is_404(client, app, tmp_path):
    app.config["DESKTOP_UPDATE_DIR"] = str(tmp_path)
    assert client.get("/desktop-updates/latest.json").status_code == 404
    assert client.get("/desktop-updates/VolkaPortal-Setup-0.1.5-win-x64.exe").status_code == 404
