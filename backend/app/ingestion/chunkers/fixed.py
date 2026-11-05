from app.config.pipeline import PipelineConfig
from app.models import Chunk, SourceFile

from .common import LineTable, line_split


class FixedChunker:
    name = "fixed"
    version = "fixed:1.0.0"

    def __init__(self, config: PipelineConfig | None = None, **_: object):
        self.config = config or PipelineConfig(chunker="fixed")

    def chunk(self, file: SourceFile) -> list[Chunk]:
        table = LineTable.from_text(file.content)
        if not table.lines:
            return []
        return line_split(
            file, table, 1, len(table.lines), self.config, version=self.version, overlap=True
        )
