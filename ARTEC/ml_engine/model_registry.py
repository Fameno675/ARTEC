"""Sauvegarde et versionnement des modèles (joblib + métadonnées + somme SHA-256).

artifacts/<nom>/<version>/model.joblib
artifacts/<nom>/<version>/metadata.json
artifacts/<nom>/latest.txt          (pointeur ; permet le retour arrière)

SÉCURITÉ : joblib repose sur pickle. Ne charger que des artefacts produits par
ARTEC ; la somme SHA-256 est vérifiée avant tout chargement.
"""
from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import joblib

from .schemas import ENGINE_VERSION


class ModelNotFoundError(FileNotFoundError):
    pass


class ModelLoadError(RuntimeError):
    pass


class ModelIntegrityError(ModelLoadError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ModelRegistry:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else Path(__file__).parent / "artifacts"

    def list_versions(self, name: str) -> List[str]:
        d = self.root / name
        return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else []

    def save(self, name: str, bundle, metadata: Optional[dict] = None, set_latest: bool = True) -> str:
        import numpy, pandas, sklearn
        version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        d = self.root / name / version
        d.mkdir(parents=True, exist_ok=False)
        path = d / "model.joblib"
        joblib.dump(bundle, path)
        meta = {
            "name": name, "version": version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sha256": _sha256(path),
            "engine_version": ENGINE_VERSION,
            "python": platform.python_version(),
            "sklearn": sklearn.__version__, "pandas": pandas.__version__, "numpy": numpy.__version__,
        }
        meta.update(metadata or {})
        (d / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        if set_latest:
            self.set_latest(name, version)
        return version

    def set_latest(self, name: str, version: str) -> None:
        """Pointe 'latest' vers une version (retour arrière = ré-appeler avec l'ancienne version)."""
        if not (self.root / name / version / "model.joblib").exists():
            raise ModelNotFoundError(f"{name}/{version} inexistant")
        (self.root / name / "latest.txt").write_text(version, encoding="utf-8")

    def resolve(self, name: str, version: str = "latest") -> str:
        if version != "latest":
            return version
        p = self.root / name / "latest.txt"
        if not p.exists():
            raise ModelNotFoundError(f"Aucun modèle '{name}' enregistré")
        return p.read_text(encoding="utf-8").strip()

    def load(self, name: str, version: str = "latest") -> Tuple[object, dict]:
        version = self.resolve(name, version)
        d = self.root / name / version
        mp, jp = d / "model.joblib", d / "metadata.json"
        if not mp.exists() or not jp.exists():
            raise ModelNotFoundError(f"{name}/{version} introuvable")
        try:
            meta = json.loads(jp.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ModelLoadError(f"Métadonnées illisibles : {exc}") from exc
        if _sha256(mp) != meta.get("sha256"):
            raise ModelIntegrityError(f"Somme SHA-256 invalide pour {name}/{version} (fichier modifié ou corrompu)")
        try:
            return joblib.load(mp), meta
        except Exception as exc:
            raise ModelLoadError(f"Chargement impossible de {name}/{version} : {exc}") from exc
