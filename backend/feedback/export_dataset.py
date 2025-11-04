import argparse
import asyncio
from pathlib import Path

from backend.feedback import export_dataset


async def main(output: Path) -> None:
    count = await export_dataset(output)
    print(f"Exported {count} feedback records to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export feedback dataset to JSONL for fine-tuning.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("feedback_dataset.jsonl"),
        help="Path to the output JSONL file",
    )
    args = parser.parse_args()
    asyncio.run(main(args.output))
