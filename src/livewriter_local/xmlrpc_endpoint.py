"""XML-RPC method dispatch for the legacy blogging APIs."""

from datetime import datetime, timezone
import logging
from xmlrpc.client import DateTime, Fault

from .auth import verify_password

logger = logging.getLogger(__name__)


class ApiFault(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _rpc_date(value: str | None):
    if not value:
        return DateTime(datetime.utcnow().strftime("%Y%m%dT%H:%M:%S"))
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return DateTime(parsed.strftime("%Y%m%dT%H:%M:%S"))
    except ValueError:
        return DateTime(datetime.utcnow().strftime("%Y%m%dT%H:%M:%S"))


class XmlRpcApi:
    def __init__(self, config, storage, blogger=None):
        self.config = config
        self.storage = storage
        self.blogger = blogger

    def _authenticate(self, username: str, password: str) -> None:
        if username != self.config.username or not verify_password(password, self.config.password_hash):
            raise ApiFault(403, "Authentication failed")

    def _blog(self) -> dict:
        return {"blogid": self.config.blog_id, "blogName": self.config.blog_name, "url": self.config.blog_url}

    def call(self, method: str, params: tuple):
        try:
            if method == "blogger.getUsersBlogs":
                if len(params) != 3:
                    raise ApiFault(400, "blogger.getUsersBlogs expects 3 parameters")
                _, username, password = params
                self._authenticate(username, password)
                return [self._blog()]
            if method == "blogger.getUserInfo":
                if len(params) != 3:
                    raise ApiFault(400, "blogger.getUserInfo expects 3 parameters")
                _, username, password = params
                self._authenticate(username, password)
                return {"nickname": username, "userid": username, "url": self.config.blog_url,
                        "email": "", "lastname": "", "firstname": username}
            if method == "metaWeblog.getCategories":
                if len(params) != 3:
                    raise ApiFault(400, "metaWeblog.getCategories expects 3 parameters")
                _, username, password = params
                self._authenticate(username, password)
                return [{"categoryName": name, "description": name, "htmlUrl": self.config.blog_url,
                         "rssUrl": ""} for name in self.storage.categories()]
            if method == "metaWeblog.newPost":
                if len(params) != 5:
                    raise ApiFault(400, "metaWeblog.newPost expects 5 parameters")
                blog_id, username, password, fields, publish = params
                self._check_blog(blog_id)
                self._authenticate(username, password)
                if not isinstance(fields, dict):
                    raise ApiFault(400, "post must be an XML-RPC struct")
                post = self.storage.create_post(fields, bool(publish), self.config.blog_url)
                if publish and self.blogger:
                    remote_id = self.blogger.publish(post)
                    self.storage.update_post_metadata(post["postid"], {
                        "blogger_post_id": remote_id, "blogger_is_draft": False,
                    })
                return post["postid"]
            if method == "metaWeblog.getPost":
                if len(params) != 3:
                    raise ApiFault(400, "metaWeblog.getPost expects 3 parameters")
                post_id, username, password = params
                self._authenticate(username, password)
                post = self.storage.get_post(str(post_id), self.config.blog_url)
                if post is None:
                    raise ApiFault(404, "Post not found")
                return self._wire_post(post)
            if method == "metaWeblog.editPost":
                if len(params) != 5:
                    raise ApiFault(400, "metaWeblog.editPost expects 5 parameters")
                post_id, username, password, fields, publish = params
                self._authenticate(username, password)
                if not isinstance(fields, dict):
                    raise ApiFault(400, "post must be an XML-RPC struct")
                post = self.storage.edit_post(str(post_id), fields, bool(publish), self.config.blog_url)
                if post is None:
                    raise ApiFault(404, "Post not found")
                if self.blogger and (publish or post.get("blogger_post_id")):
                    remote_id = self.blogger.publish(post, post.get("blogger_post_id"), is_draft=not bool(publish))
                    self.storage.update_post_metadata(post["postid"], {
                        "blogger_post_id": remote_id, "blogger_is_draft": not bool(publish),
                    })
                return True
            if method == "metaWeblog.getRecentPosts":
                if len(params) != 4:
                    raise ApiFault(400, "metaWeblog.getRecentPosts expects 4 parameters")
                blog_id, username, password, count = params
                self._check_blog(blog_id)
                self._authenticate(username, password)
                return [self._wire_post(post) for post in self.storage.recent_posts(int(count), self.config.blog_url)]
            if method == "metaWeblog.newMediaObject":
                if len(params) != 4:
                    raise ApiFault(400, "metaWeblog.newMediaObject expects 4 parameters")
                blog_id, username, password, media = params
                self._check_blog(blog_id)
                self._authenticate(username, password)
                if not isinstance(media, dict) or not isinstance(media.get("bits"), bytes):
                    raise ApiFault(400, "media struct must contain binary bits")
                if len(media["bits"]) > self.config.max_upload_bytes:
                    raise ApiFault(413, "Media upload exceeds configured limit")
                stored = self.storage.save_media(str(media.get("name", "upload")),
                                                 str(media.get("type", "")), media["bits"])
                stored["url"] = self.config.blog_url.rstrip("/") + "/media/" + stored["name"]
                return stored
            if method == "blogger.deletePost":
                if len(params) != 5:
                    raise ApiFault(400, "blogger.deletePost expects 5 parameters")
                _, post_id, username, password, _ = params
                self._authenticate(username, password)
                if not self.storage.delete_post(str(post_id)):
                    raise ApiFault(404, "Post not found")
                return True
            raise ApiFault(404, f"Unknown XML-RPC method: {method}")
        except ApiFault:
            raise
        except (TypeError, ValueError, OverflowError) as error:
            raise ApiFault(400, str(error)) from error
        except Exception as error:
            logger.exception("XML-RPC method failed: %s", method)
            raise ApiFault(500, "Internal server error") from error

    def _check_blog(self, blog_id) -> None:
        if str(blog_id) != self.config.blog_id:
            raise ApiFault(404, "Blog not found")

    @staticmethod
    def _wire_post(post: dict) -> dict:
        result = dict(post)
        result["dateCreated"] = _rpc_date(post.get("created_at"))
        if post.get("published_at"):
            result["date_created_gmt"] = _rpc_date(post["published_at"])
        return result