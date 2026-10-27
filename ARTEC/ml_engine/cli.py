"""Usage : python -m ml_engine.cli fichier.csv|xlsx [--out resultat.json] [--batch-id ID]"""
import argparse
import json

from . import analyze_batch


def main():
    ap = argparse.ArgumentParser(description="Analyse d'un lot ARTEC (CSV/XLSX)")
    ap.add_argument("path")
    ap.add_argument("--out")
    ap.add_argument("--batch-id")
    a = ap.parse_args()
    res = analyze_batch(a.path, metadata={"batch_id": a.batch_id} if a.batch_id else None)
    txt = json.dumps(res, ensure_ascii=False, indent=2, allow_nan=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt)
        print(f"Statut : {res['status']} | lignes : {res['total_observations']} | valides : "
              f"{res['valid_observations']} | rejetées : {res['rejected_observations']} | -> {a.out}")
    else:
        print(txt)


if __name__ == "__main__":
    main()
