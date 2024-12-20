import os
import webbrowser
import google_auth_oauthlib.flow
import googleapiclient.discovery

def authenticate_youtube_api():
    """Authenticate and return the YouTube API service instance."""
    api_service_name = "youtube"
    api_version = "v3"
    client_secrets_file = "client_secrets.json"  # Ensure this file exists in your project directory

    # Set the default browser to Chrome
    chrome_path = "C:/Program Files/Google/Chrome/Application/chrome.exe"  # Update path if necessary
    webbrowser.register('chrome', None, webbrowser.BackgroundBrowser(chrome_path))
    os.environ["BROWSER"] = "chrome"

    # OAuth 2.0 authorization flow
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        client_secrets_file,
        scopes=["https://www.googleapis.com/auth/youtube.force-ssl"]
    )

    credentials = flow.run_local_server(port=8080)  # Opens Chrome for user authentication
    return googleapiclient.discovery.build(api_service_name, api_version, credentials=credentials)
