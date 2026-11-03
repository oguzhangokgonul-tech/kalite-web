using System.Diagnostics;
using System.Security.Cryptography;

namespace VolkaPortal.Desktop;

internal static class UpdateClient
{
    private const string BaseUrl = "https://volkaportal.com/desktop-updates/";
    private const string PublicKeyBase64 = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE31qix+xSEF2ixcUYwwu/mfOXF0t74mUW0mZcYcp+UTgled1qr5fMZNLPVuDKcsQPEEwIY2XwfQ4coOXFAsw8ew==";
    private static readonly HttpClient Client = new(new HttpClientHandler
    {
        AllowAutoRedirect = false,
        UseCookies = false
    }) { Timeout = TimeSpan.FromSeconds(30) };
    internal static string FailureMarkerPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "VolkaPortal", "Updates", "last-update-failure.txt");

    internal static async Task<UpdateManifest?> CheckAsync(CancellationToken cancellationToken = default)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(8));
        using var response = await Client.GetAsync(BaseUrl + "latest.json",
            HttpCompletionOption.ResponseHeadersRead, timeout.Token);
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength is > 16_384)
            throw new InvalidDataException("Sürüm bildirimi çok büyük.");

        await using var stream = await response.Content.ReadAsStreamAsync(timeout.Token);
        using var buffer = new MemoryStream();
        var chunk = new byte[4096];
        int read;
        while ((read = await stream.ReadAsync(chunk, timeout.Token)) > 0)
        {
            if (buffer.Length + read > 16_384)
                throw new InvalidDataException("Sürüm bildirimi çok büyük.");
            buffer.Write(chunk, 0, read);
        }

        var manifest = UpdateManifest.Parse(
            System.Text.Encoding.UTF8.GetString(buffer.ToArray()),
            Convert.FromBase64String(PublicKeyBase64));
        var installed = typeof(UpdateClient).Assembly.GetName().Version ?? new Version(0, 0);
        return manifest.IsNewerThan(installed) ? manifest : null;
    }

    internal static async Task<string> DownloadAsync(UpdateManifest manifest,
        CancellationToken cancellationToken = default)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromMinutes(5));
        var directory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "VolkaPortal", "Updates");
        Directory.CreateDirectory(directory);
        var destination = Path.Combine(directory, manifest.Filename);
        if (File.Exists(destination) && await MatchesAsync(destination, manifest, timeout.Token))
            return destination;

        var temporary = Path.Combine(directory, $"{Guid.NewGuid():N}.part");
        try
        {
            using var response = await Client.GetAsync(BaseUrl + manifest.Filename,
                HttpCompletionOption.ResponseHeadersRead, timeout.Token);
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength is long length && length != manifest.Size)
                throw new InvalidDataException("Kurucu boyutu sürüm bildirimiyle eşleşmiyor.");

            await using (var source = await response.Content.ReadAsStreamAsync(timeout.Token))
            await using (var target = new FileStream(temporary, FileMode.CreateNew,
                FileAccess.Write, FileShare.None, 64 * 1024, true))
            {
                var chunk = new byte[64 * 1024];
                long total = 0;
                int read;
                while ((read = await source.ReadAsync(chunk, timeout.Token)) > 0)
                {
                    total += read;
                    if (total > manifest.Size)
                        throw new InvalidDataException("Kurucu beklenenden büyük.");
                    await target.WriteAsync(chunk.AsMemory(0, read), timeout.Token);
                }
                if (total != manifest.Size)
                    throw new InvalidDataException("Kurucu indirmesi tamamlanmadı.");
            }

            if (!await MatchesAsync(temporary, manifest, timeout.Token))
                throw new InvalidDataException("Kurucu bütünlük denetimini geçemedi.");
            File.Move(temporary, destination, true);
            return destination;
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }

    private static async Task<bool> MatchesAsync(string path, UpdateManifest manifest,
        CancellationToken cancellationToken)
    {
        var file = new FileInfo(path);
        if (file.Length != manifest.Size) return false;
        await using var stream = File.OpenRead(path);
        var hash = await SHA256.HashDataAsync(stream, cancellationToken);
        return CryptographicOperations.FixedTimeEquals(hash,
            Convert.FromHexString(manifest.Sha256));
    }

    internal static void StartInstaller(string path)
    {
        if (File.Exists(FailureMarkerPath)) File.Delete(FailureMarkerPath);
        _ = Process.Start(new ProcessStartInfo(path)
        {
            UseShellExecute = true,
            Arguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NORESTARTAPPLICATIONS /AUTOUPDATE"
        }) ?? throw new InvalidOperationException("Kurucu başlatılamadı.");
    }
}
