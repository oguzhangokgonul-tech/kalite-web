namespace VolkaPortal.Desktop;

internal static class UrlPolicy
{
    internal const string Home = "https://volkaportal.com/login";

    internal static bool IsPortal(string? value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) ||
            uri.Scheme != Uri.UriSchemeHttps || uri.Port != 443 ||
            !string.IsNullOrEmpty(uri.UserInfo))
            return false;

        var host = uri.IdnHost.ToLowerInvariant();
        if (host == "volkaportal.com")
            return true;

        const string suffix = ".volkaportal.com";
        if (!host.EndsWith(suffix, StringComparison.Ordinal))
            return false;

        var tenant = host[..^suffix.Length];
        return tenant.Length is > 0 and <= 63 &&
            tenant[0] != '-' && tenant[^1] != '-' &&
            tenant.All(c => char.IsAsciiLetterLower(c) || char.IsAsciiDigit(c) || c == '-');
    }

    internal static bool IsExternalWeb(string? value) =>
        Uri.TryCreate(value, UriKind.Absolute, out var uri) &&
        uri.Scheme == Uri.UriSchemeHttps &&
        string.IsNullOrEmpty(uri.UserInfo);

    internal static bool IsMailto(string? value) =>
        Uri.TryCreate(value, UriKind.Absolute, out var uri) &&
        uri.Scheme == Uri.UriSchemeMailto;
}
