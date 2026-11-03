using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace VolkaPortal.Desktop;

internal sealed record UpdateManifest(Version Version, string Filename, string Sha256, long Size)
{
    private static readonly Regex VersionPattern = new(@"^\d+\.\d+\.\d+$", RegexOptions.CultureInvariant);
    private static readonly Regex HashPattern = new(@"^[0-9a-f]{64}$", RegexOptions.CultureInvariant);

    internal static UpdateManifest Parse(string json, ReadOnlySpan<byte> publicKey)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        var versionText = root.GetProperty("version").GetString() ?? "";
        var filename = root.GetProperty("filename").GetString() ?? "";
        var sha256 = root.GetProperty("sha256").GetString() ?? "";
        var size = root.GetProperty("size").GetInt64();
        var signatureText = root.GetProperty("signature").GetString() ?? "";

        if (!VersionPattern.IsMatch(versionText) ||
            !Version.TryParse(versionText, out var version) ||
            filename != $"VolkaPortal-Setup-{versionText}-win-x64.exe" ||
            !HashPattern.IsMatch(sha256) || size is <= 0 or > 209_715_200)
            throw new InvalidDataException("Geçersiz masaüstü sürüm bildirimi.");

        var payload = Encoding.UTF8.GetBytes($"{versionText}\n{filename}\n{sha256}\n{size}\n");
        byte[] signature;
        try { signature = Convert.FromBase64String(signatureText); }
        catch (FormatException error) { throw new InvalidDataException("Geçersiz sürüm imzası.", error); }

        using var verifier = ECDsa.Create();
        verifier.ImportSubjectPublicKeyInfo(publicKey, out _);
        if (!verifier.VerifyData(payload, signature, HashAlgorithmName.SHA256,
            DSASignatureFormat.Rfc3279DerSequence))
            throw new InvalidDataException("Sürüm bildiriminin imzası doğrulanamadı.");

        return new UpdateManifest(version, filename, sha256, size);
    }

    internal bool IsNewerThan(Version installed) => Version > installed;
}
