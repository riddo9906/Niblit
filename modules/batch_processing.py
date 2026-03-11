#!/usr/bin/env python3
"""
Batch Processing - Efficient bulk operations

Collects interactions/operations and processes them in batches for
efficiency. Reduces overhead and improves throughput.

Features:
- Configurable batch size
- Periodic flush
- Async support
- Metrics tracking
- Error handling
"""

import asyncio
import logging
from typing import List, Any, Callable, Optional
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger("BatchProcessing")


@dataclass
class BatchItem:
    """Item in a batch."""
    data: Any
    added_at: float = field(default_factory=lambda: datetime.now().timestamp())


class Batcher:
    """
    Generic batch processor.

    Features:
    - Automatic flushing based on size or time
    - Async processing
    - Error handling and retry
    """

    def __init__(
        self,
        batch_size: int = 32,
        flush_interval_seconds: int = 5,
        processor: Optional[Callable] = None
    ):
        """
        Initialize batcher.

        Args:
            batch_size: Number of items before auto-flush
            flush_interval_seconds: Seconds before auto-flush
            processor: Async function to process batch
        """
        self.batch: List[BatchItem] = []
        self.batch_size = batch_size
        self.flush_interval = flush_interval_seconds
        self.processor = processor
        self.metrics = {
            "batches_processed": 0,
            "items_processed": 0,
            "errors": 0,
        }
        log.debug(f"Batcher initialized: size={batch_size}, interval={flush_interval_seconds}s")

    async def add(self, item: Any) -> bool:
        """
        Add item to batch.

        Args:
            item: Item to add

        Returns:
            True if batch flushed
        """
        self.batch.append(BatchItem(item))

        if len(self.batch) >= self.batch_size:
            await self.flush()
            return True

        return False

    async def flush(self) -> int:
        """
        Flush current batch to processor.

        Returns:
            Number of items processed
        """
        if not self.batch:
            return 0

        items_count = len(self.batch)
        batch_to_process = self.batch.copy()
        self.batch.clear()

        if self.processor:
            try:
                log.info(f"[BATCH] Processing {items_count} items")
                await self.processor(batch_to_process)
                self.metrics["batches_processed"] += 1
                self.metrics["items_processed"] += items_count
            except Exception as e:
                log.error(f"[BATCH] Processing failed: {e}")
                self.metrics["errors"] += 1
                self.batch.extend(batch_to_process)
                return 0

        return items_count

    async def periodic_flush_loop(self):
        """Run periodic flush in background."""
        try:
            while True:
                await asyncio.sleep(self.flush_interval)
                if self.batch:
                    await self.flush()
        except asyncio.CancelledError:
            if self.batch:
                await self.flush()
            raise

    def get_stats(self) -> dict:
        """Get batcher statistics."""
        return {
            "pending_items": len(self.batch),
            "batch_size": self.batch_size,
            **self.metrics,
        }


class LearningBatcher(Batcher):
    """Specialized batcher for learning interactions."""

    def __init__(
        self,
        batch_size: int = 32,
        flush_interval_seconds: int = 5
    ):
        async def process_learning_batch(batch: List[BatchItem]):
            """Process learning batch."""
            for item in batch:
                interaction = item.data
                log.debug(f"Learning from: {interaction}")

        super().__init__(batch_size, flush_interval_seconds, process_learning_batch)

    async def add_interaction(self, interaction: dict) -> bool:
        """Add interaction to learning batch."""
        return await self.add(interaction)

    def add_sync(self, interaction: dict) -> bool:
        """Synchronous add for backward compatibility."""
        self.batch.append(BatchItem(interaction))
        if len(self.batch) >= self.batch_size:
            try:
                asyncio.create_task(self.flush())
            except RuntimeError:
                pass
            return True
        return False


if __name__ == "__main__":
    async def test():
        async def mock_processor(batch: List[BatchItem]):
            """Mock processor."""
            await asyncio.sleep(0.1)
            print(f"Processing batch of {len(batch)} items")

        batcher = Batcher(batch_size=5, flush_interval_seconds=2, processor=mock_processor)

        for i in range(12):
            await batcher.add(f"item_{i}")
            print(f"Added item {i}")

        await batcher.flush()

        print(f"Stats: {batcher.get_stats()}")

    asyncio.run(test())
