# LiveWriter Local

A local-first publishing server implementing the XML-RPC methods commonly needed by Windows Live Writer, with an optional Render deployment and Google Blogger publish mirror. The server stores post bodies as HTML files, metadata and media records in SQLite, and uploaded media in the configured data directory.

## Requirements

- Python 3.11 or newer
- A Windows Live Writer installation for compatibility testing (not required to run unit tests)

## Install and start

From the project directory, install the package and its test extras:

```powershell
py -3.11 -m pip install -e ".[dev]"
livewriter-local --init-config
livewriter-local
```

The initializer prompts for a local username and password, then writes `config.json` with a scrypt password hash. The server defaults to `127.0.0.1:8080`; data is created under `data/`. To use a different config path, pass `--config path\to\config.json` to either command.

### Windows deployment

Run the following in PowerShell from the project directory:

```powershell
cd "D:\live writer"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m livewriter_local --init-config
python -m livewriter_local
```

Keep the server terminal open while using Live Writer. Stop it with `Ctrl+C`; start it again with `python -m livewriter_local`. The companion library is at `http://127.0.0.1:8080/` when using the default port. In Live Writer, choose **Other services** / **MetaWeblog API** and use the homepage URL, XML-RPC endpoint, configured username, and password shown below. No firewall rule or public hosting is needed for loopback use.

If another program already uses port `8080`, change `port` in your private `config.json` and change `blog_url` to use that same port. For example, use `8081` in both places and set Live Writer's URLs to `http://127.0.0.1:8081/` and `http://127.0.0.1:8081/xmlrpc`. Restart the server after changing config. Do not change the host from `127.0.0.1` for normal same-computer use.

### Render cloud deployment

The repository includes `render.yaml` for a paid Render Starter web service with a persistent disk mounted at `/var/data`. A persistent disk is important: the free ephemeral filesystem can lose the SQLite database and uploaded files on restart or redeploy. Render requires a GitHub, GitLab, or Bitbucket repository; this working folder is not currently connected to a Git repository. Create a private repository and push this project, then choose **New + → Blueprint** in Render and connect that repository. Set `LW_USERNAME` and `LW_PASSWORD_HASH` when prompted. Generate a new cloud password hash locally without echoing the password:

```powershell
python -c "from getpass import getpass; from livewriter_local.auth import hash_password; print(hash_password(getpass('New cloud password: ')))"
```

Copy the printed hash into Render as `LW_PASSWORD_HASH`; enter a matching username as `LW_USERNAME`. Use a new cloud password, not one previously pasted into chat. `config.json` and `data/` are ignored by Git and must not be committed.

Render provides HTTPS and `RENDER_EXTERNAL_URL`; the service listens on Render's `PORT` and stores data on its persistent disk automatically. The cloud dashboard and post previews require HTTP Basic authentication using the same local username/password. XML-RPC calls continue to authenticate using the protocol credentials. Media URLs returned to posts are public so remote readers can load images; use only media you intend to publish. Keep Blogger OAuth secrets in Render's Environment settings, never in the repository.

### Blogger mirror

Live Writer continues publishing to LiveWriter Local. When a post is published here, the server also creates or updates its Blogger copy; local drafts are not sent until published. Editing an already mirrored post updates its existing Blogger post. The post body is copied as HTML and categories/tags become Blogger labels. Images uploaded to this service remain hosted by this service, so the public Render URL and persistent disk must remain available for Blogger readers to load those image links.

1. In Google Cloud Console, create/select a project, enable **Blogger API v3**, and configure the OAuth consent screen for your Google account.
2. Create an OAuth client ID of type **Desktop app** and download its client-secret JSON to this project folder. Do not commit it.
3. Run `python -m pip install -e .` then `python scripts/authorize_blogger.py client_secret.json`. Sign into the Google account that owns the target blog and approve Blogger access. Copy the printed client ID, client secret, and refresh token into Render environment variables `BLOGGER_CLIENT_ID`, `BLOGGER_CLIENT_SECRET`, and `BLOGGER_REFRESH_TOKEN`.
4. Find the target blog's numeric Blogger API blog ID and set it as `BLOGGER_BLOG_ID`. Set `BLOGGER_ENABLED=true` in Render, save the environment changes, and redeploy.
5. Publish a test entry from Live Writer, confirm it appears in Blogger, then edit and republish it to verify it updates rather than duplicates.

Google OAuth apps in **Testing** status can issue refresh tokens that expire after seven days. For ongoing mirroring, configure the consent screen and app publishing/verification appropriate to your account, or expect to repeat authorization when Google expires the token. Google may show an unverified-app warning during setup. Never send the refresh token or client secret in chat or commit them to source control.

This cloud deployment is publicly reachable. The dashboard and post previews are password-protected; XML-RPC writes require credentials, and media URLs are public by design. Use HTTPS URLs in Live Writer and keep the Render service private to your own account. The web service and persistent disk may incur charges; check Render's current pricing before creating it.

The Blogger mirror applies to new posts and future edits after it is enabled. Existing posts in your current local `data/` directory are not automatically uploaded to Render or Blogger; export/import or republish those separately after deployment.

Open `http://127.0.0.1:8080/` for the local post list. The XML-RPC endpoint is `http://127.0.0.1:8080/xmlrpc`, and RSD discovery is available at `http://127.0.0.1:8080/rsd`. In Windows Live Writer, use the MetaWeblog API and provide the XML-RPC endpoint, username, and password when manual configuration is needed.

To bind beyond loopback, set both a non-loopback `host` and `allow_remote` to `true` in the config. This is intentionally explicit; the server logs a warning when remote binding is enabled. Do not expose this initial implementation directly to the public internet.

Export content to a portable ZIP or import that ZIP into another configured data directory:

```powershell
livewriter-local-export --output backup.zip
livewriter-local-import --config clean-instance.json --input backup.zip
```

The archive preserves stable post IDs, post metadata, HTML bodies, and uploaded media. Import rejects unexpected archive paths, duplicate IDs, and overwrites.

## Implemented methods

- `blogger.getUsersBlogs`, `blogger.getUserInfo`, `blogger.deletePost`
- `metaWeblog.getCategories`, `newPost`, `getPost`, `editPost`, `getRecentPosts`, `newMediaObject`

Post writes require the configured local credentials. XML-RPC request size, media upload size, unsupported methods, malformed XML, and failed authentication are handled with XML-RPC faults. Full request bodies and credentials are not logged. Deleted posts are moved to `data/trash/`.

Run tests with:

```powershell
py -3.11 -m pytest
```

## Compatibility status

Automated tests establish the implemented API behavior only. No Windows Live Writer release has been tested against this project yet, so this repository does not claim legacy-client compatibility. The RSD response and endpoint can also be configured manually in the client. Record the exact client version and sanitized request traces before claiming compatibility.

Current MVP limitations: AtomPub, configurable deletion policies, multi-user accounts, and actual Windows Live Writer client compatibility verification are not implemented. The service is designed for local preservation and experimentation, not public multi-user hosting.