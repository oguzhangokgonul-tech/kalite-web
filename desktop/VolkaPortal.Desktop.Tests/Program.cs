using VolkaPortal.Desktop;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

var accepted = new[]
{
    "https://volkaportal.com/login",
    "https://erprefabrik.volkaportal.com/aksiyonlar",
    "https://sagiroglucelik.volkaportal.com:443/dokuman-yonetimi"
};
var rejected = new[]
{
    "http://volkaportal.com/login",
    "https://volkaportal.com.evil.test/login",
    "https://a.b.volkaportal.com/login",
    "https://user@volkaportal.com/login",
    "https://volkaportal.com:8443/login",
    "file:///C:/secret.txt",
    "javascript:alert(1)",
    "https://-bad.volkaportal.com/login"
};

foreach (var url in accepted)
    if (!UrlPolicy.IsPortal(url)) throw new Exception($"Expected portal URL: {url}");
foreach (var url in rejected)
    if (UrlPolicy.IsPortal(url)) throw new Exception($"Unexpected portal URL: {url}");

Console.WriteLine($"URL policy: {accepted.Length + rejected.Length} checks passed.");

using var signer = ECDsa.Create(ECCurve.NamedCurves.nistP256);
var publicKey = signer.ExportSubjectPublicKeyInfo();
const string version = "0.1.6";
const string filename = "VolkaPortal-Setup-0.1.6-win-x64.exe";
var sha256 = new string('a', 64);
const long size = 42;
var payload = Encoding.UTF8.GetBytes($"{version}\n{filename}\n{sha256}\n{size}\n");
var signature = signer.SignData(payload, HashAlgorithmName.SHA256,
    DSASignatureFormat.Rfc3279DerSequence);
var valid = JsonSerializer.Serialize(new
{
    version, filename, sha256, size, signature = Convert.ToBase64String(signature)
});
var parsed = UpdateManifest.Parse(valid, publicKey);
if (!parsed.IsNewerThan(new Version(0, 1, 5)) ||
    parsed.IsNewerThan(new Version(0, 1, 6)))
    throw new Exception("Version comparison failed.");

foreach (var invalid in new[]
{
    valid.Replace(sha256, new string('b', 64), StringComparison.Ordinal),
    valid.Replace(filename, "other.exe", StringComparison.Ordinal),
    valid.Replace("0.1.6", "0.1.4", StringComparison.Ordinal),
    valid.Replace("\"size\":42", "\"size\":999999999", StringComparison.Ordinal)
})
{
    try { _ = UpdateManifest.Parse(invalid, publicKey); }
    catch (InvalidDataException) { continue; }
    throw new Exception("Invalid manifest accepted.");
}
Console.WriteLine("Update manifest: signature, filename, size, version checks passed.");

if (args.Length == 1)
{
    const string releasePublicKey = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE31qix+xSEF2ixcUYwwu/mfOXF0t74mUW0mZcYcp+UTgled1qr5fMZNLPVuDKcsQPEEwIY2XwfQ4coOXFAsw8ew==";
    var release = UpdateManifest.Parse(File.ReadAllText(args[0]),
        Convert.FromBase64String(releasePublicKey));
    var installer = Path.Combine(Path.GetDirectoryName(args[0])!, release.Filename);
    if (new FileInfo(installer).Length != release.Size ||
        !string.Equals(Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(installer))),
            release.Sha256, StringComparison.OrdinalIgnoreCase))
        throw new Exception("Release installer does not match manifest.");
    Console.WriteLine($"Release package verified: {release.Filename}");
}
