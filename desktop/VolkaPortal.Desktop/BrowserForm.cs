using System.Diagnostics;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace VolkaPortal.Desktop;

internal sealed class BrowserForm : Form
{
    private const double DefaultZoomFactor = 0.67;
    private readonly WebView2 browser = new() { Dock = DockStyle.Fill };
    private readonly Panel updateBanner = new() { Dock = DockStyle.Top, Height = 42, Visible = false };
    private readonly Label updateDot = new() { AutoSize = false, Dock = DockStyle.Left, Width = 18, Text = "●", TextAlign = ContentAlignment.MiddleLeft };
    private readonly Label updateLabel = new() { AutoSize = false, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft };
    private readonly Button updateButton = new() { Dock = DockStyle.Right, Width = 145, Text = "Sistemi güncelle" };
    private readonly System.Windows.Forms.Timer updateCheckTimer = new() { Interval = 60 * 60 * 1000 };
    private readonly System.Windows.Forms.Timer updatePulseTimer = new() { Interval = 900 };
    private readonly bool checkUpdates;
    private CoreWebView2Environment? environment;
    private UpdateManifest? availableUpdate;
    private bool pulseBright;

    internal BrowserForm(bool checkUpdates = true)
    {
        this.checkUpdates = checkUpdates;
        Text = "VolkaPortal";
        Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        Width = 1280;
        Height = 850;
        MinimumSize = new Size(640, 480);
        StartPosition = FormStartPosition.CenterScreen;

        updateBanner.BackColor = Color.FromArgb(239, 247, 255);
        updateBanner.Padding = new Padding(14, 5, 14, 5);
        updateLabel.Text = "Güncelleme gerekli";
        updateLabel.Font = new Font(Font, FontStyle.Regular);
        updateButton.FlatStyle = FlatStyle.Flat;
        updateButton.FlatAppearance.BorderColor = Color.FromArgb(127, 172, 223);
        updateButton.ForeColor = Color.FromArgb(15, 75, 145);
        updateButton.BackColor = Color.White;
        updateButton.Cursor = Cursors.Hand;
        updateButton.Width = Math.Max(145, TextRenderer.MeasureText(updateButton.Text, updateButton.Font).Width + 26);
        updateBanner.Height = Math.Max(42, updateButton.PreferredSize.Height + 10);
        ApplyUpdateBannerColors();
        new ToolTip().SetToolTip(updateButton, "Doğrulanmış yeni sürümü indirip kurar");
        updateBanner.Controls.Add(updateLabel);
        updateBanner.Controls.Add(updateDot);
        updateBanner.Controls.Add(updateButton);
        Controls.Add(browser);
        Controls.Add(updateBanner);
        updateButton.Click += async (_, _) => await InstallUpdateAsync();
        SystemColorsChanged += (_, _) =>
        {
            ApplyUpdateBannerColors();
            if (SystemInformation.HighContrast)
                updatePulseTimer.Stop();
            else if (availableUpdate is not null)
                updatePulseTimer.Start();
        };
        updateCheckTimer.Tick += async (_, _) => await CheckForUpdatesAsync();
        updatePulseTimer.Tick += (_, _) =>
        {
            pulseBright = !pulseBright;
            updateDot.ForeColor = pulseBright
                ? Color.FromArgb(16, 93, 184) : updateBanner.BackColor;
        };
        Shown += async (_, _) =>
        {
            ShowPreviousUpdateFailure();
            if (browser.CoreWebView2 is null)
                await InitializeAsync(null, null);
            if (this.checkUpdates)
            {
                updateCheckTimer.Start();
                await CheckForUpdatesAsync();
            }
        };
        FormClosed += (_, _) =>
        {
            updateCheckTimer.Dispose();
            updatePulseTimer.Dispose();
        };
    }

    private void ApplyUpdateBannerColors()
    {
        updateBanner.BackColor = SystemInformation.HighContrast
            ? SystemColors.Window : Color.FromArgb(239, 247, 255);
        updateLabel.ForeColor = SystemInformation.HighContrast
            ? SystemColors.WindowText : Color.FromArgb(19, 79, 152);
        updateDot.ForeColor = SystemInformation.HighContrast
            ? SystemColors.WindowText : Color.FromArgb(16, 93, 184);
        updateButton.ForeColor = SystemInformation.HighContrast
            ? SystemColors.ControlText : Color.FromArgb(15, 75, 145);
        updateButton.BackColor = SystemInformation.HighContrast
            ? SystemColors.Control : Color.White;
        updateButton.FlatAppearance.BorderColor = SystemInformation.HighContrast
            ? SystemColors.WindowText : Color.FromArgb(127, 172, 223);
    }

    private static void ShowPreviousUpdateFailure()
    {
        try
        {
            if (!File.Exists(UpdateClient.FailureMarkerPath)) return;
            File.Delete(UpdateClient.FailureMarkerPath);
            MessageBox.Show("Önceki güncelleme tamamlanamadı. VolkaPortal mevcut sürümle açıldı; " +
                "bir süre sonra yeniden deneyin veya destek ekibine bildirin.",
                "VolkaPortal güncellemesi", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        catch (IOException error) { Debug.WriteLine(error.Message); }
        catch (UnauthorizedAccessException error) { Debug.WriteLine(error.Message); }
    }

    private async Task CheckForUpdatesAsync()
    {
        try
        {
            var release = await UpdateClient.CheckAsync();
            if (IsDisposed) return;
            availableUpdate = release;
            updateBanner.Visible = release is not null;
            if (release is not null && !SystemInformation.HighContrast)
                updatePulseTimer.Start();
            else
                updatePulseTimer.Stop();
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"Güncelleme denetimi yapılamadı: {ex.Message}");
        }
    }

    private async Task InstallUpdateAsync()
    {
        var release = availableUpdate;
        if (release is null) return;
        if (MessageBox.Show(
            $"VolkaPortal {release.Version} sürümü kurulacak. Kaydedilmemiş çalışmalarınızı önce tamamlayın. Devam edilsin mi?",
            "VolkaPortal güncellemesi", MessageBoxButtons.YesNo, MessageBoxIcon.Question,
            MessageBoxDefaultButton.Button2) != DialogResult.Yes)
            return;

        updateButton.Enabled = false;
        updateButton.Text = "İndiriliyor...";
        updatePulseTimer.Stop();
        try
        {
            var path = await UpdateClient.DownloadAsync(release);
            UpdateClient.StartInstaller(path);
            Application.Exit();
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Güncelleme başlatılamadı: {ex.Message}",
                "VolkaPortal", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            updateButton.Enabled = true;
            updateButton.Text = "Sistemi güncelle";
            if (!SystemInformation.HighContrast) updatePulseTimer.Start();
        }
    }

    private async Task InitializeAsync(CoreWebView2Environment? shared, string? startUrl)
    {
        try
        {
            var userData = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "VolkaPortal", "WebView2");
            environment = shared ?? await CoreWebView2Environment.CreateAsync(userDataFolder: userData);
            await browser.EnsureCoreWebView2Async(environment);
            browser.ZoomFactor = DefaultZoomFactor;
            ConfigureBrowser();
            if (startUrl is not null)
                browser.CoreWebView2.Navigate(startUrl);
            else if (shared is null)
                browser.CoreWebView2.Navigate(UrlPolicy.Home);
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Masaüstü penceresi açılamadı: {ex.Message}",
                "VolkaPortal", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void ConfigureBrowser()
    {
        var core = browser.CoreWebView2;
        core.Settings.IsWebMessageEnabled = false;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.AreHostObjectsAllowed = false;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.IsZoomControlEnabled = true;

        core.NavigationStarting += (_, e) =>
        {
            if (UrlPolicy.IsPortal(e.Uri)) return;
            e.Cancel = true;
            if (UrlPolicy.IsExternalWeb(e.Uri) || UrlPolicy.IsMailto(e.Uri))
                OpenExternal(e.Uri);
        };
        core.FrameNavigationStarting += (_, e) =>
        {
            if (!UrlPolicy.IsPortal(e.Uri) && e.Uri != "about:blank") e.Cancel = true;
        };
        core.ServerCertificateErrorDetected += (_, e) =>
            e.Action = CoreWebView2ServerCertificateErrorAction.Cancel;
        core.PermissionRequested += (_, e) =>
            e.State = CoreWebView2PermissionState.Deny;
        core.DownloadStarting += (_, e) =>
        {
            if (!UrlPolicy.IsPortal(e.DownloadOperation.Uri)) e.Cancel = true;
        };
        core.NewWindowRequested += async (_, e) =>
        {
            if (!UrlPolicy.IsPortal(e.Uri))
            {
                e.Handled = true;
                if (UrlPolicy.IsExternalWeb(e.Uri) || UrlPolicy.IsMailto(e.Uri))
                    OpenExternal(e.Uri);
                return;
            }

            var deferral = e.GetDeferral();
            BrowserForm? child = null;
            try
            {
                child = new BrowserForm(false);
                await child.InitializeAsync(environment, null);
                if (child.browser.CoreWebView2 is null)
                {
                    e.Handled = true;
                    child.Dispose();
                    return;
                }
                e.NewWindow = child.browser.CoreWebView2;
                child.Show(this);
            }
            catch
            {
                e.Handled = true;
                child?.Dispose();
            }
            finally
            {
                deferral.Complete();
            }
        };
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (browser.CoreWebView2 is not null)
        {
            if (keyData is Keys.F5 or (Keys.Control | Keys.R))
            {
                browser.CoreWebView2.Reload();
                return true;
            }
            if (keyData == (Keys.Alt | Keys.Left) && browser.CanGoBack)
            {
                browser.GoBack();
                return true;
            }
            if (keyData == (Keys.Alt | Keys.Right) && browser.CanGoForward)
            {
                browser.GoForward();
                return true;
            }
        }
        return base.ProcessCmdKey(ref msg, keyData);
    }

    private static void OpenExternal(string address)
    {
        try
        {
            var target = new Uri(address);
            if (MessageBox.Show($"Dış bağlantı açılacak:\n{target.Host}\n\nVarsayılan tarayıcıda devam edilsin mi?",
                "VolkaPortal", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
                return;
            Process.Start(new ProcessStartInfo(address) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Bağlantı açılamadı: {ex.Message}", "VolkaPortal",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }
}
