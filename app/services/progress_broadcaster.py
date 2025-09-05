"""
Progress Broadcasting Service for Real-time Updates

This module provides WebSocket and Server-Sent Events (SSE) endpoints 
for broadcasting real-time progress updates of batch TTS jobs.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Set, Optional, Any, AsyncGenerator
import weakref

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse


class ProgressBroadcaster:
    """
    Manages real-time progress broadcasting via WebSocket and SSE
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # WebSocket connections
        self.websocket_connections: Set[WebSocket] = set()
        
        # SSE connections - using weak references to avoid memory leaks
        self.sse_connections: Set[asyncio.Queue] = set()
        
        # Connection tracking
        self.connection_count = 0
        
    async def connect_websocket(self, websocket: WebSocket) -> bool:
        """
        Connect a new WebSocket client
        
        Args:
            websocket: WebSocket connection
            
        Returns:
            bool: True if connected successfully
        """
        try:
            await websocket.accept()
            self.websocket_connections.add(websocket)
            self.connection_count += 1
            
            # Send initial connection confirmation
            await websocket.send_json({
                "type": "connection",
                "status": "connected",
                "timestamp": datetime.now().isoformat(),
                "message": "WebSocket connection established"
            })
            
            self.logger.info(f"WebSocket client connected. Total connections: {len(self.websocket_connections)}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to accept WebSocket connection: {e}")
            return False
    
    async def disconnect_websocket(self, websocket: WebSocket):
        """
        Disconnect a WebSocket client
        
        Args:
            websocket: WebSocket connection to disconnect
        """
        if websocket in self.websocket_connections:
            self.websocket_connections.remove(websocket)
            self.logger.info(f"WebSocket client disconnected. Total connections: {len(self.websocket_connections)}")
    
    def connect_sse(self) -> asyncio.Queue:
        """
        Connect a new SSE client
        
        Returns:
            asyncio.Queue: Queue for receiving progress updates
        """
        queue = asyncio.Queue(maxsize=100)  # Limit queue size to prevent memory issues
        self.sse_connections.add(queue)
        self.connection_count += 1
        
        self.logger.info(f"SSE client connected. Total connections: {len(self.sse_connections)}")
        return queue
    
    def disconnect_sse(self, queue: asyncio.Queue):
        """
        Disconnect an SSE client
        
        Args:
            queue: Queue to remove
        """
        if queue in self.sse_connections:
            self.sse_connections.remove(queue)
            self.logger.info(f"SSE client disconnected. Total connections: {len(self.sse_connections)}")
    
    async def broadcast_progress(self, progress_data: Dict[str, Any]):
        """
        Broadcast progress update to all connected clients
        
        Args:
            progress_data: Progress data dictionary
        """
        if not self.websocket_connections and not self.sse_connections:
            return  # No clients connected
        
        message = {
            "type": "progress",
            "data": progress_data,
            "timestamp": datetime.now().isoformat()
        }
        
        # Broadcast to WebSocket clients
        await self._broadcast_websocket(message)
        
        # Broadcast to SSE clients
        await self._broadcast_sse(message)
    
    async def broadcast_job_status(self, job_id: str, status: str, additional_data: Optional[Dict[str, Any]] = None):
        """
        Broadcast job status change to all connected clients
        
        Args:
            job_id: Job identifier
            status: New job status
            additional_data: Additional data to include
        """
        message = {
            "type": "job_status",
            "data": {
                "job_id": job_id,
                "status": status,
                **(additional_data or {})
            },
            "timestamp": datetime.now().isoformat()
        }
        
        await self._broadcast_websocket(message)
        await self._broadcast_sse(message)
    
    async def broadcast_system_message(self, message_type: str, message_text: str, level: str = "info"):
        """
        Broadcast system message to all connected clients
        
        Args:
            message_type: Type of message (e.g., "info", "warning", "error")
            message_text: Message content
            level: Message level
        """
        message = {
            "type": "system",
            "data": {
                "message_type": message_type,
                "message": message_text,
                "level": level
            },
            "timestamp": datetime.now().isoformat()
        }
        
        await self._broadcast_websocket(message)
        await self._broadcast_sse(message)
    
    async def _broadcast_websocket(self, message: Dict[str, Any]):
        """
        Broadcast message to WebSocket clients
        
        Args:
            message: Message to broadcast
        """
        if not self.websocket_connections:
            return
        
        # Create a copy of connections to avoid modification during iteration
        connections = list(self.websocket_connections)
        disconnected = []
        
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except WebSocketDisconnect:
                disconnected.append(websocket)
            except Exception as e:
                self.logger.error(f"Error sending WebSocket message: {e}")
                disconnected.append(websocket)
        
        # Remove disconnected clients
        for websocket in disconnected:
            await self.disconnect_websocket(websocket)
    
    async def _broadcast_sse(self, message: Dict[str, Any]):
        """
        Broadcast message to SSE clients
        
        Args:
            message: Message to broadcast
        """
        if not self.sse_connections:
            return
        
        # Format message for SSE
        sse_data = f"data: {json.dumps(message, ensure_ascii=False)}\n\n"
        
        # Create a copy of connections to avoid modification during iteration
        connections = list(self.sse_connections)
        disconnected = []
        
        for queue in connections:
            try:
                if queue.full():
                    # Remove oldest message if queue is full
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                
                await queue.put(sse_data)
                
            except Exception as e:
                self.logger.error(f"Error sending SSE message: {e}")
                disconnected.append(queue)
        
        # Remove disconnected clients
        for queue in disconnected:
            self.disconnect_sse(queue)
    
    async def handle_websocket_connection(self, websocket: WebSocket):
        """
        Handle a WebSocket connection lifecycle
        
        Args:
            websocket: WebSocket connection
        """
        connected = await self.connect_websocket(websocket)
        if not connected:
            return
        
        try:
            while True:
                # Listen for messages from client
                try:
                    data = await websocket.receive_json()
                    await self._handle_client_message(websocket, data)
                except Exception as e:
                    self.logger.error(f"Error handling WebSocket message: {e}")
                    break
                    
        except WebSocketDisconnect:
            self.logger.info("WebSocket client disconnected")
        except Exception as e:
            self.logger.error(f"WebSocket connection error: {e}")
        finally:
            await self.disconnect_websocket(websocket)
    
    async def _handle_client_message(self, websocket: WebSocket, data: Dict[str, Any]):
        """
        Handle message from WebSocket client
        
        Args:
            websocket: WebSocket connection
            data: Message data
        """
        message_type = data.get("type")
        
        if message_type == "ping":
            # Respond to ping with pong
            await websocket.send_json({
                "type": "pong",
                "timestamp": datetime.now().isoformat()
            })
        
        elif message_type == "subscribe":
            # Client wants to subscribe to specific job updates
            job_id = data.get("job_id")
            if job_id:
                # Store subscription (for future enhancement)
                self.logger.info(f"Client subscribed to job {job_id}")
        
        else:
            self.logger.warning(f"Unknown message type from client: {message_type}")
    
    async def generate_sse_stream(self, queue: asyncio.Queue) -> AsyncGenerator[str, None]:
        """
        Generate SSE stream from queue
        
        Args:
            queue: Message queue
            
        Yields:
            str: SSE formatted messages
        """
        try:
            # Send initial connection message
            initial_message = {
                "type": "connection",
                "status": "connected",
                "timestamp": datetime.now().isoformat(),
                "message": "SSE connection established"
            }
            yield f"data: {json.dumps(initial_message, ensure_ascii=False)}\n\n"
            
            # Stream messages from queue
            while True:
                try:
                    # Wait for message with timeout to allow connection cleanup
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield message
                    
                except asyncio.TimeoutError:
                    # Send keepalive message
                    keepalive = {
                        "type": "keepalive",
                        "timestamp": datetime.now().isoformat()
                    }
                    yield f"data: {json.dumps(keepalive, ensure_ascii=False)}\n\n"
                    
        except asyncio.CancelledError:
            self.logger.info("SSE stream cancelled")
            raise
        except Exception as e:
            self.logger.error(f"SSE stream error: {e}")
        finally:
            self.disconnect_sse(queue)
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """
        Get connection statistics
        
        Returns:
            Dict with connection statistics
        """
        return {
            "websocket_connections": len(self.websocket_connections),
            "sse_connections": len(self.sse_connections),
            "total_connections": len(self.websocket_connections) + len(self.sse_connections),
            "lifetime_connections": self.connection_count
        }
    
    async def shutdown(self):
        """
        Shutdown the progress broadcaster and clean up connections
        """
        self.logger.info("Shutting down progress broadcaster")
        
        # Close all WebSocket connections
        websockets = list(self.websocket_connections)
        for websocket in websockets:
            try:
                await websocket.close()
            except:
                pass
        self.websocket_connections.clear()
        
        # Clear SSE connections
        self.sse_connections.clear()
        
        self.logger.info("Progress broadcaster shutdown complete")


# Global broadcaster instance
progress_broadcaster = ProgressBroadcaster()


def get_progress_broadcaster() -> ProgressBroadcaster:
    """
    Get the global progress broadcaster instance
    
    Returns:
        ProgressBroadcaster: Global instance
    """
    return progress_broadcaster