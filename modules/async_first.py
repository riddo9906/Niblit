#!/usr/bin/env python3
"""
Async-First Architecture - Non-blocking operations throughout

Enables:
- Concurrent processing
- Better resource utilization
- Proper cancellation support
- Task coordination
"""

import logging
import asyncio
from typing import Optional, Any, List, Callable
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger("AsyncFirst")


@dataclass
class AsyncTask:
    """Represents an async task."""
    name: str
    coro: Any
    timeout: Optional[float] = None
    priority: int = 0
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


class AsyncTaskCoordinator:
    """
    Coordinates async tasks with proper lifecycle management.
    
    Features:
    - Task grouping
    - Timeout handling
    - Priority scheduling
    - Cancellation support
    - Result aggregation
    """
    
    def __init__(self):
        self.active_tasks: set[asyncio.Task] = set()
        self.completed_tasks: List[tuple[str, Any]] = []
        self.failed_tasks: List[tuple[str, Exception]] = []
        log.debug("AsyncTaskCoordinator initialized")
    
    async def run_task(
        self,
        name: str,
        coro: Any,
        timeout: Optional[float] = None
    ) -> Optional[Any]:
        """
        Run a single async task with timeout.
        
        Args:
            name: Task name
            coro: Coroutine to run
            timeout: Timeout in seconds
            
        Returns:
            Task result or None
        """
        try:
            log.debug(f"[ASYNC] Starting task: {name}")
            
            task = asyncio.create_task(coro)
            self.active_tasks.add(task)
            
            try:
                if timeout:
                    result = await asyncio.wait_for(task, timeout=timeout)
                else:
                    result = await task
                
                self.completed_tasks.append((name, result))
                log.info(f"[ASYNC] Task completed: {name}")
                return result
                
            except asyncio.TimeoutError:
                log.error(f"[ASYNC] Task timeout: {name} ({timeout}s)")
                task.cancel()
                self.failed_tasks.append((name, TimeoutError(f"Task {name} timed out")))
                return None
            except asyncio.CancelledError:
                log.info(f"[ASYNC] Task cancelled: {name}")
                return None
            finally:
                self.active_tasks.discard(task)
                
        except Exception as e:
            log.error(f"[ASYNC] Task error: {name}: {e}", exc_info=True)
            self.failed_tasks.append((name, e))
            return None
    
    async def run_concurrent(
        self,
        tasks: List[AsyncTask],
        return_exceptions: bool = False
    ) -> dict[str, Any]:
        """
        Run multiple tasks concurrently.
        
        Uses asyncio.TaskGroup (Python 3.11+) for proper cleanup.
        
        Args:
            tasks: List of AsyncTask objects
            return_exceptions: If True, exceptions are returned as results
            
        Returns:
            Dictionary of {task_name: result}
        """
        log.debug(f"[ASYNC] Starting {len(tasks)} concurrent tasks")
        
        results = {}
        
        try:
            async with asyncio.TaskGroup() as tg:
                task_map = {}
                for async_task in sorted(tasks, key=lambda t: t.priority, reverse=True):
                    try:
                        if async_task.timeout:
                            coro = asyncio.wait_for(
                                async_task.coro,
                                timeout=async_task.timeout
                            )
                        else:
                            coro = async_task.coro
                        
                        task = tg.create_task(coro)
                        task_map[task] = async_task.name
                        log.debug(f"[ASYNC] Task queued: {async_task.name}")
                    except Exception as e:
                        if return_exceptions:
                            results[async_task.name] = e
                        else:
                            raise
        except ExceptionGroup as eg:
            log.error(f"[ASYNC] Multiple tasks failed: {len(eg.exceptions)} errors")
            if return_exceptions:
                for task_name, exc in zip(task_map.values(), eg.exceptions):
                    results[task_name] = exc
            else:
                raise
        
        log.info(f"[ASYNC] Concurrent execution completed: {len(results)} results")
        return results
    
    async def cancel_all(self):
        """Cancel all active tasks."""
        log.info(f"[ASYNC] Cancelling {len(self.active_tasks)} active tasks")
        for task in self.active_tasks:
            task.cancel()
        
        # Wait for cancellation
        if self.active_tasks:
            await asyncio.gather(*self.active_tasks, return_exceptions=True)
    
    def get_stats(self) -> dict[str, Any]:
        """Get task execution statistics."""
        return {
            "active_tasks": len(self.active_tasks),
            "completed_tasks": len(self.completed_tasks),
            "failed_tasks": len(self.failed_tasks),
            "total_tasks": len(self.completed_tasks) + len(self.failed_tasks),
            "success_rate": (
                len(self.completed_tasks) / 
                max(len(self.completed_tasks) + len(self.failed_tasks), 1)
            )
        }


class AsyncHandler:
    """Main async handler for commands."""
    
    def __init__(self):
        self.coordinator = AsyncTaskCoordinator()
        log.debug("AsyncHandler initialized")
    
    async def handle_concurrent_commands(
        self,
        commands: List[tuple[str, Callable]]
    ) -> dict[str, Any]:
        """
        Handle multiple commands concurrently.
        
        Args:
            commands: List of (name, coroutine_function) tuples
            
        Returns:
            Dictionary of {command_name: result}
        """
        tasks = [
            AsyncTask(
                name=name,
                coro=coro(),
                timeout=5.0,
                priority=0
            )
            for name, coro in commands
        ]
        
        return await self.coordinator.run_concurrent(tasks, return_exceptions=True)


# Example usage
if __name__ == "__main__":
    async def slow_task(name: str, delay: float) -> str:
        await asyncio.sleep(delay)
        return f"Task {name} completed"
    
    async def test():
        handler = AsyncHandler()
        
        tasks = [
            AsyncTask("task1", slow_task("1", 1.0)),
            AsyncTask("task2", slow_task("2", 2.0)),
            AsyncTask("task3", slow_task("3", 0.5)),
        ]
        
        results = await handler.coordinator.run_concurrent(tasks)
        print(f"Results: {results}")
        print(f"Stats: {handler.coordinator.get_stats()}")
    
    asyncio.run(test())
