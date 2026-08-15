from __future__ import annotations

import argparse
import os
from pathlib import Path

from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an OpenAI vector store and upload the synthetic ITRA PDFs."
    )
    parser.add_argument("--name", default="ITRA Normalizer Demo Evidence")
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "data/raw_pdfs")
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY must be set in the shell; never pass it as an argument.")
    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDF files found in {args.pdf_dir}")

    client = OpenAI()
    vector_store = client.vector_stores.create(name=args.name)
    print(f"Created vector store: {vector_store.id}")
    for pdf in pdfs:
        with pdf.open("rb") as handle:
            uploaded = client.vector_stores.files.upload_and_poll(
                vector_store_id=vector_store.id,
                file=handle,
                attributes={"fixture": True, "filename": pdf.name},
            )
        print(f"Uploaded {pdf.name}: {uploaded.status}")
    print(f"OPENAI_VECTOR_STORE_ID={vector_store.id}")


if __name__ == "__main__":
    main()
