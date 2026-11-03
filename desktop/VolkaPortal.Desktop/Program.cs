using Microsoft.Web.WebView2.Core;

namespace VolkaPortal.Desktop;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();

        try
        {
            _ = CoreWebView2Environment.GetAvailableBrowserVersionString();
        }
        catch (WebView2RuntimeNotFoundException)
        {
            MessageBox.Show("Microsoft Edge WebView2 Runtime gerekli. Lütfen Microsoft'un resmi WebView2 Runtime paketini yükleyin.",
                "VolkaPortal", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        Application.Run(new BrowserForm());
    }
}
