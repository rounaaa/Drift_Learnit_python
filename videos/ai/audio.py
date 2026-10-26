import contextlib
import http.client
import ipaddress
import logging
import math
import shutil
import socket
import ssl
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_DURATION_SECONDS = 10 * 60
DOWNLOAD_TIMEOUT_SECONDS = 20
ALLOWED_MEDIA_TYPES = {
    "audio/m4a",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-m4a",
    "audio/x-mp3",
    "audio/x-wav",
    "video/mp4",
    "video/quicktime",
}


class AudioSourceError(Exception):
    pass


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, address, port):
        super().__init__(
            host=address,
            port=port,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
        self.server_hostname = hostname

    def connect(self):
        self.sock = self._create_connection(
            (self.host, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=self.server_hostname
        )


def _max_file_size():
    return int(getattr(settings, "VIDEO_SUMMARY_MAX_FILE_SIZE", MAX_FILE_SIZE))


def _max_duration():
    return int(
        getattr(
            settings,
            "VIDEO_SUMMARY_MAX_DURATION_SECONDS",
            MAX_DURATION_SECONDS,
        )
    )


def _validate_remote_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise AudioSourceError("Le lien source contient un port invalide.") from exc
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in (None, 80, 443)
    ):
        raise AudioSourceError("Le lien source doit être une URL HTTP(S) publique valide.")

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise AudioSourceError("Le nom de domaine du média est introuvable.") from exc

    resolved = list(dict.fromkeys(address[4][0] for address in addresses))
    if not resolved or any(not ipaddress.ip_address(address).is_global for address in resolved):
        raise AudioSourceError("Les liens vers des adresses locales ou privées sont refusés.")
    return parsed, resolved[0], port or (443 if parsed.scheme == "https" else 80)


def _download_remote_file(url, destination):
    parsed, address, port = _validate_remote_url(url)
    hostname = parsed.hostname.encode("idna").decode("ascii")
    connection_type = (
        _PinnedHTTPSConnection
        if parsed.scheme == "https"
        else http.client.HTTPConnection
    )
    if parsed.scheme == "https":
        connection = connection_type(hostname, address, port)
    else:
        connection = connection_type(
            host=address,
            port=port,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
    target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    request_headers = {
        "Host": parsed.netloc.encode("idna").decode("ascii"),
        "User-Agent": "LearnIt-video-audio/1.0",
        "Accept": "audio/*,video/*",
        "Connection": "close",
    }
    try:
        connection.request("GET", target, headers=request_headers)
        response = connection.getresponse()
    except (http.client.HTTPException, TimeoutError, OSError) as exc:
        connection.close()
        logger.warning("Échec du téléchargement d'un média distant: %s", exc)
        raise AudioSourceError("Le téléchargement du média a échoué ou a expiré.") from exc
    try:
        if response.status != 200:
            raise AudioSourceError("Le serveur du média n'a pas retourné de fichier.")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type not in ALLOWED_MEDIA_TYPES:
            raise AudioSourceError("Le lien ne pointe pas vers un fichier audio/vidéo reconnu.")
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                size = int(content_length)
            except ValueError as exc:
                raise AudioSourceError("La taille annoncée par le serveur est invalide.") from exc
            if size < 0:
                raise AudioSourceError("La taille annoncée par le serveur est invalide.")
            if size > _max_file_size():
                raise AudioSourceError(
                    "Le média dépasse la taille maximale autorisée de "
                    f"{_max_file_size() / (1024 * 1024):g} Mo."
                )

        total = 0
        with destination.open("wb") as output:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _max_file_size():
                    raise AudioSourceError(
                        "Le média dépasse la taille maximale autorisée de "
                        f"{_max_file_size() / (1024 * 1024):g} Mo."
                    )
                output.write(chunk)
        if total == 0:
            raise AudioSourceError("Le fichier média distant est vide.")
    finally:
        response.close()
        connection.close()


def _copy_stored_field(file_field, destination):
    total = 0
    with file_field.open("rb") as source, destination.open("wb") as output:
        while True:
            chunk = source.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _max_file_size():
                raise AudioSourceError(
                    "Le média dépasse la taille maximale autorisée de "
                    f"{_max_file_size() / (1024 * 1024):g} Mo."
                )
            output.write(chunk)
    if not total:
        raise AudioSourceError("Le fichier source est vide.")


def _duration_seconds(source_path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise AudioSourceError(
            "ffprobe est introuvable. Installez ffmpeg et ajoutez-le au PATH."
        )
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                "-protocol_whitelist",
                "file,pipe",
                str(source_path),
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
        duration = float(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.exception("Impossible de lire la durée du fichier audio/vidéo.")
        raise AudioSourceError("Le fichier source est illisible ou invalide.") from exc
    if not math.isfinite(duration) or duration <= 0 or duration > _max_duration():
        raise AudioSourceError(
            "La durée maximale autorisée pour la source est de "
            f"{_max_duration() / 60:g} minutes."
        )
    return duration


@contextlib.contextmanager
def prepared_audio(summary):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioSourceError(
            "ffmpeg est introuvable. Installez ffmpeg et ajoutez-le au PATH."
        )

    with tempfile.TemporaryDirectory(prefix="learnit-audio-") as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / "source"
        if summary.source_file:
            _copy_stored_field(summary.source_file, source_path)
        else:
            video_url = getattr(summary.video, "video_url", "")
            if video_url:
                _download_remote_file(video_url, source_path)
            elif summary.video.video_file:
                _copy_stored_field(summary.video.video_file, source_path)
            else:
                raise AudioSourceError(
                    "Aucun fichier source n'est disponible; fournissez un MP4, MP3, WAV ou M4A."
                )

        duration = _duration_seconds(source_path)
        wav_path = temp_path / "audio.wav"
        try:
            subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(source_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-f",
                    "wav",
                    str(wav_path),
                ],
                capture_output=True,
                check=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.exception("Échec de l'extraction audio avec ffmpeg.")
            raise AudioSourceError("Impossible d'extraire l'audio de la source.") from exc
        yield wav_path, duration
