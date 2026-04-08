# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional, Tuple, Union

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

# Set of command names that modify Live's state. Must mirror the keys of
# AbletonMCP._modifying_commands in AbletonMCP_Remote_Script/__init__.py.
# When adding a new modifying command, add it to BOTH places.
MODIFYING_COMMANDS = {
    "create_midi_track", "create_audio_track", "set_track_name",
    "create_clip", "add_notes_to_clip", "set_clip_name",
    "set_tempo", "fire_clip", "stop_clip",
    "start_playback", "stop_playback", "load_browser_item",
    "remove_notes_from_clip", "delete_clip",
    "duplicate_clip_to", "set_track_volume", "set_track_pan",
    "set_track_send", "fire_scene", "undo",
    "batch_commands",
    # Tier 2 primitives
    "set_time_signature", "set_clip_loop", "set_clip_length",
    "set_track_arm", "set_track_mute", "set_track_solo",
    "delete_track", "set_master_volume", "set_device_parameter",
    "create_scene", "set_scene_name", "set_scene_tempo",
    # Tier 1 cross-track duplicate
    "duplicate_clip_cross_track",
    # Tier 5 arrangement view (BETA)
    "add_clip_to_arrangement", "set_arrangement_loop", "add_arrangement_locator",
}


@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(15.0)  # Increased timeout for operations that might take longer
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        # Check if this is a state-modifying command
        is_modifying_command = command_type in MODIFYING_COMMANDS
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")

            # Send the command, with one warm-path reconnect retry if Ableton
            # restarted or the socket was silently dropped between calls.
            payload = json.dumps(command).encode('utf-8')
            try:
                self.sock.sendall(payload)
            except (BrokenPipeError, ConnectionResetError, OSError) as send_err:
                logger.warning(f"Socket send failed ({send_err}); attempting one reconnect")
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
                if not self.connect():
                    raise ConnectionError("Reconnect to Ableton failed")
                self.sock.sendall(payload)
            logger.info(f"Command sent, waiting for response...")
            
            # For state-modifying commands, add a small delay to give Ableton time to process
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            # Set timeout based on command type
            timeout = 15.0 if is_modifying_command else 10.0
            self.sock.settimeout(timeout)
            
            # Receive the response
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            
            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))
            
            # For state-modifying commands, add another small delay after receiving response
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

    def send_batch(self, commands: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send a batch of commands to Ableton in one round-trip.

        ``commands`` is a list of ``{"type": str, "params": dict}``. The remote
        script executes them sequentially on Live's main thread inside a single
        scheduled closure, so the whole batch is atomic and a single ``undo``
        will revert all of it. Stops on the first failure and returns partial
        results.
        """
        return self.send_command("batch_commands", {"commands": commands})


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        
        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")
        
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCP",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection
    
    if _ableton_connection is not None:
        try:
            # Test the connection with a simple ping
            # We'll try to send an empty message, which should fail if the connection is dead
            # but won't affect Ableton if it's alive
            _ableton_connection.sock.settimeout(1.0)
            _ableton_connection.sock.sendall(b'')
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None
    
    # Connection doesn't exist or is invalid, create a new one
    if _ableton_connection is None:
        # Try to connect up to 3 times with a short delay between attempts
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host="localhost", port=9877)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    
                    # Validate connection with a simple command
                    try:
                        # Get session info as a test
                        _ableton_connection.send_command("get_session_info")
                        logger.info("Connection validated successfully")
                        return _ableton_connection
                    except Exception as e:
                        logger.error(f"Connection validation failed: {str(e)}")
                        _ableton_connection.disconnect()
                        _ableton_connection = None
                        # Continue to next attempt
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None
            
            # Wait before trying again, but only if we have more attempts left
            if attempt < max_attempts:
                import time
                time.sleep(1.0)
        
        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")
    
    return _ableton_connection


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"

@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.
    
    Parameters:
    - track_index: The index of the track to get information about
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_info", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.
    
    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.
    
    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_name", {"track_index": track_index, "name": name})
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.
    
    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_clip", {
            "track_index": track_index, 
            "clip_index": clip_index, 
            "length": length
        })
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
def add_notes_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes
        })
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.
    
    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_tempo", {"tempo": tempo})
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.
    
    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri
        })
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
            else:
                devices = result.get("devices_after", [])
                return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
        else:
            return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"

@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"

@mcp.tool()
def get_clip_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Get all MIDI notes from a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip

    Returns note data including pitch, start_time, duration, velocity, and mute for each note.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_notes", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip notes: {str(e)}")
        return f"Error getting clip notes: {str(e)}"

@mcp.tool()
def remove_notes_from_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    from_time: float = 0.0,
    from_pitch: int = 0,
    time_span: float = 99999.0,
    pitch_span: int = 128
) -> str:
    """
    Remove MIDI notes from a clip within a specified range.
    By default removes ALL notes. Use parameters to target specific ranges.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - from_time: Start time in beats (default: 0.0 = beginning)
    - from_pitch: Lowest MIDI pitch to remove (default: 0)
    - time_span: Duration in beats to clear (default: 99999.0 = all)
    - pitch_span: Number of pitches above from_pitch to clear (default: 128 = all)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("remove_notes_from_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "from_time": from_time,
            "from_pitch": from_pitch,
            "time_span": time_span,
            "pitch_span": pitch_span
        })
        return f"Removed notes from clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error removing notes from clip: {str(e)}")
        return f"Error removing notes from clip: {str(e)}"

@mcp.tool()
def delete_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Delete a clip from a clip slot, leaving the slot empty.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot to clear
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Deleted clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error deleting clip: {str(e)}")
        return f"Error deleting clip: {str(e)}"

@mcp.tool()
def duplicate_clip_to(ctx: Context, track_index: int, clip_index: int, target_clip_index: int) -> str:
    """
    Duplicate a clip to another clip slot on the same track.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The source clip slot index
    - target_clip_index: The destination clip slot index (must be empty)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_clip_to", {
            "track_index": track_index,
            "clip_index": clip_index,
            "target_clip_index": target_clip_index
        })
        return f"Duplicated clip from slot {clip_index} to slot {target_clip_index} on track {track_index}"
    except Exception as e:
        logger.error(f"Error duplicating clip: {str(e)}")
        return f"Error duplicating clip: {str(e)}"

@mcp.tool()
def set_track_volume(ctx: Context, track_index: int, volume: float) -> str:
    """
    Set the volume of a track.

    Parameters:
    - track_index: The index of the track
    - volume: Volume level from 0.0 (silent) to 1.0 (max). Default is ~0.85.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_volume", {
            "track_index": track_index,
            "volume": volume
        })
        return f"Set track {track_index} volume to {result.get('volume', volume)}"
    except Exception as e:
        logger.error(f"Error setting track volume: {str(e)}")
        return f"Error setting track volume: {str(e)}"

@mcp.tool()
def set_track_pan(ctx: Context, track_index: int, pan: float) -> str:
    """
    Set the panning of a track.

    Parameters:
    - track_index: The index of the track
    - pan: Panning from -1.0 (full left) to 1.0 (full right). 0.0 is center.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_pan", {
            "track_index": track_index,
            "pan": pan
        })
        return f"Set track {track_index} panning to {result.get('panning', pan)}"
    except Exception as e:
        logger.error(f"Error setting track panning: {str(e)}")
        return f"Error setting track panning: {str(e)}"

@mcp.tool()
def set_track_send(ctx: Context, track_index: int, send_index: int, value: float) -> str:
    """
    Set a send amount on a track (for routing to return tracks).

    Parameters:
    - track_index: The index of the track
    - send_index: The index of the send (0 = Send A, 1 = Send B, etc.)
    - value: Send amount from 0.0 (none) to 1.0 (full)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_send", {
            "track_index": track_index,
            "send_index": send_index,
            "value": value
        })
        return f"Set track {track_index} send {send_index} to {result.get('value', value)}"
    except Exception as e:
        logger.error(f"Error setting track send: {str(e)}")
        return f"Error setting track send: {str(e)}"

@mcp.tool()
def fire_scene(ctx: Context, scene_index: int) -> str:
    """
    Fire (launch) a scene, triggering all clips in that row across all tracks.

    Parameters:
    - scene_index: The index of the scene to fire (0-based)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_scene", {
            "scene_index": scene_index
        })
        scene_name = result.get('scene_name', '')
        return f"Fired scene {scene_index}" + (f" ({scene_name})" if scene_name else "")
    except Exception as e:
        logger.error(f"Error firing scene: {str(e)}")
        return f"Error firing scene: {str(e)}"

@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {"index": index})
        return f"Created new audio track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating audio track: {str(e)}")
        return f"Error creating audio track: {str(e)}"

@mcp.tool()
def undo(ctx: Context) -> str:
    """Undo the last action in Ableton."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("undo")
        return "Undid last action"
    except Exception as e:
        logger.error(f"Error undoing: {str(e)}")
        return f"Error undoing: {str(e)}"

@mcp.tool()
def batch_commands(ctx: Context, commands: List[Dict[str, Any]]) -> str:
    """
    Execute a list of commands in a single round-trip to Ableton.

    The whole batch runs atomically inside one main-thread closure, so a
    single subsequent ``undo`` reverts the entire sequence. Execution stops
    at the first failure and partial results are returned.

    Parameters:
    - commands: list of {"type": str, "params": dict}. Allowed types are any
      modifying or read-only command (e.g. ``create_midi_track``,
      ``add_notes_to_clip``, ``set_track_volume``). Nested ``batch_commands``
      is not allowed.

    Returns a JSON object with:
    - ``results``: list of per-command {"status", "result" or "message"}
    - ``executed``: how many ran (including the failing one if any)
    - ``total``: how many were submitted
    - ``failed_at``: index of the failure or null
    - ``error``: failure message or null
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_batch(commands)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error running batch_commands: {str(e)}")
        return f"Error running batch_commands: {str(e)}"

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.
    
    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.
    
    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })
        
        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.
    
    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"

# =====================================================================
# Tier 4 — Music theory helpers (pure Python, no remote changes needed).
# These build note arrays locally and reuse add_notes_to_clip /
# remove_notes_from_clip / get_clip_notes on the remote.
#
# Music constants and parsers live in MCP_Server/music.py so test scripts
# can import them too. We re-bind to underscore names below to keep the
# rest of this file unchanged.
# =====================================================================

from MCP_Server.music import (
    NOTE_TO_SEMITONE as _NOTE_TO_SEMITONE,
    SCALES as _SCALES,
    CHORDS as _CHORDS,
    parse_chord as _parse_chord,
    parse_scale as _parse_scale,
    RHYTHM_BEATS as _RHYTHM_BEATS,
    GRID_BEATS as _GRID_BEATS,
    DRUM_PATTERNS as _DRUM_PATTERNS,
    DEFAULT_KIT_MAP as _DEFAULT_KIT_MAP,
)
from MCP_Server import personalities as _personalities


@mcp.tool()
def add_chord_progression(
    ctx: Context,
    track_index: int,
    clip_index: int,
    chords: List[str],
    rhythm: str = "whole",
    octave: int = 4,
    velocity: int = 100,
) -> str:
    """
    Write a chord progression into an existing MIDI clip in one call.

    Parameters:
    - track_index, clip_index: target clip (must already exist; use
      ``create_clip_with_notes`` to create the clip in the same call)
    - chords: list of chord symbols, e.g. ["Cm", "Fm", "G7", "Cm"] or
      ["Fmaj7", "Em7", "Dm7", "Cmaj7"]
    - rhythm: how long each chord lasts — "whole" (4 beats), "half",
      "quarter", "eighth", "sixteenth"
    - octave: middle octave for the chord roots (4 = middle C area)
    - velocity: 0-127 MIDI velocity for every note
    """
    try:
        if rhythm not in _RHYTHM_BEATS:
            return f"rhythm must be one of {list(_RHYTHM_BEATS.keys())}"
        beats_per_chord = _RHYTHM_BEATS[rhythm]
        notes: List[Dict[str, Any]] = []
        for chord_index, symbol in enumerate(chords):
            pitches = _parse_chord(symbol, octave)
            start = chord_index * beats_per_chord
            for pitch in pitches:
                notes.append({
                    "pitch": int(pitch),
                    "start_time": float(start),
                    "duration": float(beats_per_chord),
                    "velocity": int(velocity),
                    "mute": False,
                })
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes,
        })
        return json.dumps({
            "chord_count": len(chords),
            "note_count": len(notes),
            "total_beats": len(chords) * beats_per_chord,
            "remote_result": result,
        }, indent=2)
    except Exception as e:
        logger.error(f"Error adding chord progression: {str(e)}")
        return f"Error adding chord progression: {str(e)}"


@mcp.tool()
def add_scale_run(
    ctx: Context,
    track_index: int,
    clip_index: int,
    scale: str,
    start_beat: float = 0.0,
    end_beat: float = 4.0,
    direction: str = "up",
    note_duration: float = 0.25,
    octave: int = 4,
    velocity: int = 100,
) -> str:
    """
    Write a scalar run (sequence of notes from a scale) into an existing clip.

    Parameters:
    - scale: e.g. "C minor", "F# dorian", "Eb major pentatonic"
    - start_beat, end_beat: time range in the clip
    - direction: "up", "down", or "updown"
    - note_duration: length of each note in beats (default 1/16)
    - octave: starting octave (4 = middle C)
    - velocity: 0-127

    Generates ascending/descending notes from the chosen scale, packed into
    the [start_beat, end_beat) range with ``note_duration`` per note.
    """
    try:
        root_semitone, intervals = _parse_scale(scale)
        base_pitch = (octave + 1) * 12 + root_semitone
        scale_pitches = [base_pitch + iv for iv in intervals]
        # Extend across two octaves so runs longer than 7 notes don't repeat
        scale_pitches = scale_pitches + [p + 12 for p in scale_pitches]
        if direction == "down":
            scale_pitches = list(reversed(scale_pitches))
        elif direction == "updown":
            scale_pitches = scale_pitches + list(reversed(scale_pitches))[1:-1]
        elif direction != "up":
            return "direction must be 'up', 'down', or 'updown'"
        if end_beat <= start_beat:
            return "end_beat must be greater than start_beat"
        total = end_beat - start_beat
        n_notes = max(1, int(round(total / note_duration)))
        notes: List[Dict[str, Any]] = []
        for i in range(n_notes):
            pitch = scale_pitches[i % len(scale_pitches)]
            notes.append({
                "pitch": int(pitch),
                "start_time": float(start_beat + i * note_duration),
                "duration": float(note_duration),
                "velocity": int(velocity),
                "mute": False,
            })
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes,
        })
        return json.dumps({
            "scale": scale,
            "note_count": len(notes),
            "remote_result": result,
        }, indent=2)
    except Exception as e:
        logger.error(f"Error adding scale run: {str(e)}")
        return f"Error adding scale run: {str(e)}"


@mcp.tool()
def add_drum_pattern(
    ctx: Context,
    track_index: int,
    clip_index: int,
    pattern: str = "four_on_floor",
    length: float = 4.0,
    kit_map: Optional[Dict[str, int]] = None,
    velocity: int = 100,
) -> str:
    """
    Write a preset drum pattern into an existing clip. Patterns are defined
    in 1-bar (4 beats) building blocks and tile to fill ``length``.

    Parameters:
    - pattern: "four_on_floor" | "trap" | "breakbeat" | "boom_bap"
    - length: clip length in beats (pattern tiles to fill this)
    - kit_map: optional override mapping drum names ("kick", "snare", "hat",
      "open_hat", "clap", "tom") to MIDI pitches. Defaults to General MIDI
      drum mapping (kick=36, snare=38, hat=42, open_hat=46).
    - velocity: 0-127
    """
    try:
        if pattern not in _DRUM_PATTERNS:
            return f"pattern must be one of {list(_DRUM_PATTERNS.keys())}"
        kit = dict(_DEFAULT_KIT_MAP)
        if kit_map:
            kit.update(kit_map)
        pattern_def = _DRUM_PATTERNS[pattern]
        bar_length = 4.0
        notes: List[Dict[str, Any]] = []
        n_bars = max(1, int(length // bar_length))
        for bar in range(n_bars):
            bar_offset = bar * bar_length
            for drum_key, beats in pattern_def:
                if drum_key not in kit:
                    continue
                pitch = kit[drum_key]
                for beat in beats:
                    notes.append({
                        "pitch": int(pitch),
                        "start_time": float(bar_offset + beat),
                        "duration": 0.125,
                        "velocity": int(velocity),
                        "mute": False,
                    })
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes,
        })
        return json.dumps({
            "pattern": pattern,
            "bars": n_bars,
            "note_count": len(notes),
            "remote_result": result,
        }, indent=2)
    except Exception as e:
        logger.error(f"Error adding drum pattern: {str(e)}")
        return f"Error adding drum pattern: {str(e)}"


@mcp.tool()
def quantize_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    grid: str = "1/16",
) -> str:
    """
    Quantize all notes in a clip to a grid by snapping each note's
    ``start_time`` to the nearest grid line.

    Parameters:
    - grid: "1/4" | "1/8" | "1/16" | "1/32"

    Implementation: read existing notes, round start times, then in one
    batch remove the old notes and write the new ones. The whole edit is
    atomic from Live's perspective.
    """
    try:
        if grid not in _GRID_BEATS:
            return f"grid must be one of {list(_GRID_BEATS.keys())}"
        step = _GRID_BEATS[grid]
        ableton = get_ableton_connection()
        clip_notes = ableton.send_command("get_clip_notes", {
            "track_index": track_index, "clip_index": clip_index})
        existing = clip_notes.get("notes", [])
        if not existing:
            return "Clip has no notes to quantize"
        new_notes = []
        for n in existing:
            snapped = round(float(n["start_time"]) / step) * step
            new_notes.append({
                "pitch": int(n["pitch"]),
                "start_time": float(snapped),
                "duration": float(n.get("duration", 0.25)),
                "velocity": int(n.get("velocity", 100)),
                "mute": bool(n.get("mute", False)),
            })
        batch_result = ableton.send_batch([
            {"type": "remove_notes_from_clip", "params": {
                "track_index": track_index, "clip_index": clip_index}},
            {"type": "add_notes_to_clip", "params": {
                "track_index": track_index, "clip_index": clip_index, "notes": new_notes}},
        ])
        return json.dumps({
            "grid": grid,
            "note_count": len(new_notes),
            "batch": batch_result,
        }, indent=2)
    except Exception as e:
        logger.error(f"Error quantizing clip: {str(e)}")
        return f"Error quantizing clip: {str(e)}"


@mcp.tool()
def list_personalities(ctx: Context) -> str:
    """
    List every available 'personality' style profile, grouped by role.

    Roles:
      - **solo**  — melodic / lead lines (Coltrane, Kenny G, Oscar Peterson, Miles Davis, Charlie Parker, Wayne Shorter)
      - **comp**  — chord voicings / comping (Bill Evans rootless, McCoy Tyner quartal, Herbie Hancock)
      - **bass**  — bass lines (James Jamerson, Jaco Pastorius, Pino Palladino)
      - **drums** — drum patterns (Questlove pocket, Tony Williams swing, Vinnie Colaiuta polyrhythms)

    Each personality declares a ``tempo_sweet_spot`` and a comfortable
    ``tempo_range``; outside that range the generators emit a warning and
    automatically scale density / swing to compensate.

    Use the ``key`` field as the ``personality`` argument to
    ``add_personality`` (the unified tool) or ``add_personality_solo`` (legacy).
    """
    return json.dumps(_personalities.list_personalities(), indent=2)


def _resolve_session_tempo(ableton: "AbletonConnection", explicit: Optional[float]) -> float:
    """Use the explicit tempo if given, otherwise pull the live session tempo."""
    if explicit is not None:
        return float(explicit)
    info = ableton.send_command("get_session_info")
    return float(info.get("tempo", 120.0))


@mcp.tool()
def add_personality(
    ctx: Context,
    track_index: int,
    clip_index: int,
    personality: str,
    chord_progression: List[str],
    bars_per_chord: int = 1,
    tempo: Optional[float] = None,
    octave_offset: int = 0,
    seed: Optional[int] = None,
) -> str:
    """
    Generate a part in the style of a named personality and write it into an
    existing MIDI clip. The personality's role (solo / comp / bass / drums)
    determines what kind of part is generated — see ``list_personalities``.

    Parameters:
    - track_index, clip_index: target clip (must already exist)
    - personality: one of the keys returned by ``list_personalities``
    - chord_progression: list of chord symbols, e.g. ["Cm","Ab","Eb","Bb"].
      Drum personalities ignore chord content but still use the length.
    - bars_per_chord: how many 4/4 bars each chord lasts (default 1)
    - tempo: BPM for tempo-aware generation. If omitted, the current session
      tempo is queried via ``get_session_info``. The personality's profile
      will warn (but still produce output) if this is outside its comfortable
      range, and generators will scale density / swing to compensate.
    - octave_offset: shift the personality's natural register up/down N octaves
    - seed: optional RNG seed for reproducible output. Default ``None`` =
      a different solo every call.
    """
    try:
        ableton = get_ableton_connection()
        actual_tempo = _resolve_session_tempo(ableton, tempo)
        notes, warning = _personalities.generate_personality_part(
            personality=personality,
            chord_progression=chord_progression,
            bars_per_chord=bars_per_chord,
            tempo=actual_tempo,
            octave_offset=octave_offset,
            seed=seed,
        )
        if not notes:
            return json.dumps({
                "personality": personality,
                "warning": warning,
                "error": "Generator produced no notes (empty progression?)",
            }, indent=2)
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes,
        })
        profile = _personalities.PERSONALITIES[personality.strip().lower().replace(" ", "_")]
        return json.dumps({
            "personality": profile["name"],
            "role": profile["role"],
            "note_count": len(notes),
            "tempo": actual_tempo,
            "warning": warning,
            "instrument_hint": profile.get("instrument_hint"),
            "remote_result": result,
        }, indent=2)
    except Exception as e:
        logger.error(f"Error in add_personality: {str(e)}")
        return f"Error in add_personality: {str(e)}"


@mcp.tool()
def add_personality_solo(
    ctx: Context,
    track_index: int,
    clip_index: int,
    personality: str,
    chord_progression: List[str],
    bars_per_chord: int = 1,
    tempo: Optional[float] = None,
    octave_offset: int = 0,
    seed: Optional[int] = None,
) -> str:
    """
    Legacy alias for ``add_personality`` restricted to ``solo`` personalities.
    Prefer ``add_personality`` (which auto-dispatches by role). Kept so older
    callers don't break.
    """
    return add_personality(
        ctx, track_index, clip_index, personality, chord_progression,
        bars_per_chord, tempo, octave_offset, seed,
    )


@mcp.tool()
def add_blended_personality_solo(
    ctx: Context,
    track_index: int,
    clip_index: int,
    personality_a: str,
    personality_b: str,
    ratio: float,
    chord_progression: List[str],
    bars_per_chord: int = 1,
    tempo: Optional[float] = None,
    octave_offset: int = 0,
    seed: Optional[int] = None,
) -> str:
    """
    Generate a solo from a *blended* personality — interpolated between two
    real personalities. Currently solo-only.

    Parameters:
    - personality_a, personality_b: keys of two ``solo`` personalities
    - ratio: 0.0 = all A, 1.0 = all B, 0.5 = perfectly mixed
    - all other arguments: same as ``add_personality``

    Numeric profile fields (density, swing, range bounds, velocity range,
    chord-tone emphasis, etc.) are linearly interpolated. Categorical pools
    (scale modes, phrase arc) take from A when ratio < 0.5 and B otherwise.
    """
    try:
        ableton = get_ableton_connection()
        actual_tempo = _resolve_session_tempo(ableton, tempo)
        notes = _personalities.generate_blended_solo(
            personality_a=personality_a,
            personality_b=personality_b,
            ratio=ratio,
            chord_progression=chord_progression,
            bars_per_chord=bars_per_chord,
            tempo=actual_tempo,
            octave_offset=octave_offset,
            seed=seed,
        )
        if not notes:
            return "Blended generator produced no notes"
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes,
        })
        blend = _personalities.blend_personalities(personality_a, personality_b, ratio)
        return json.dumps({
            "blend": blend["name"],
            "ratio": ratio,
            "note_count": len(notes),
            "tempo": actual_tempo,
            "remote_result": result,
        }, indent=2)
    except Exception as e:
        logger.error(f"Error in add_blended_personality_solo: {str(e)}")
        return f"Error in add_blended_personality_solo: {str(e)}"


@mcp.tool()
def transpose_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    semitones: int,
) -> str:
    """
    Transpose every note in a clip by ``semitones`` (positive = up, negative
    = down). Notes that would land outside the MIDI range [0, 127] are
    clamped.

    Implementation: read notes, mutate pitches, batch(remove + add).
    """
    try:
        ableton = get_ableton_connection()
        clip_notes = ableton.send_command("get_clip_notes", {
            "track_index": track_index, "clip_index": clip_index})
        existing = clip_notes.get("notes", [])
        if not existing:
            return "Clip has no notes to transpose"
        new_notes = []
        for n in existing:
            new_pitch = max(0, min(127, int(n["pitch"]) + int(semitones)))
            new_notes.append({
                "pitch": new_pitch,
                "start_time": float(n["start_time"]),
                "duration": float(n.get("duration", 0.25)),
                "velocity": int(n.get("velocity", 100)),
                "mute": bool(n.get("mute", False)),
            })
        batch_result = ableton.send_batch([
            {"type": "remove_notes_from_clip", "params": {
                "track_index": track_index, "clip_index": clip_index}},
            {"type": "add_notes_to_clip", "params": {
                "track_index": track_index, "clip_index": clip_index, "notes": new_notes}},
        ])
        return json.dumps({
            "semitones": semitones,
            "note_count": len(new_notes),
            "batch": batch_result,
        }, indent=2)
    except Exception as e:
        logger.error(f"Error transposing clip: {str(e)}")
        return f"Error transposing clip: {str(e)}"


# =====================================================================
# Tier 2 — Missing primitives (set_time_signature, mixer state, devices,
# scenes, master, delete_track, etc.)
# =====================================================================

@mcp.tool()
def set_time_signature(ctx: Context, numerator: int, denominator: int) -> str:
    """
    Set the song's time signature.

    Parameters:
    - numerator: top number (1-99)
    - denominator: bottom number, must be a power of 2 (1, 2, 4, 8, 16)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_time_signature", {
            "numerator": numerator,
            "denominator": denominator,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting time signature: {str(e)}")
        return f"Error setting time signature: {str(e)}"


@mcp.tool()
def set_clip_loop(
    ctx: Context,
    track_index: int,
    clip_index: int,
    loop_start: float,
    loop_end: float,
    loop_on: bool = True,
) -> str:
    """
    Set a clip's loop region (in beats) and whether the clip loops.

    Parameters:
    - track_index, clip_index: which clip
    - loop_start: loop start in beats
    - loop_end: loop end in beats (must be > loop_start)
    - loop_on: enable looping
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_loop", {
            "track_index": track_index,
            "clip_index": clip_index,
            "loop_start": loop_start,
            "loop_end": loop_end,
            "loop_on": loop_on,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting clip loop: {str(e)}")
        return f"Error setting clip loop: {str(e)}"


@mcp.tool()
def set_clip_length(ctx: Context, track_index: int, clip_index: int, length: float) -> str:
    """
    Resize a clip by moving its end_marker. Length is measured in beats from
    the clip's start_marker.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_length", {
            "track_index": track_index,
            "clip_index": clip_index,
            "length": length,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting clip length: {str(e)}")
        return f"Error setting clip length: {str(e)}"


@mcp.tool()
def set_track_arm(ctx: Context, track_index: int, arm: bool) -> str:
    """Arm or disarm a track for recording."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_arm", {"track_index": track_index, "arm": arm})
        return f"Set track {track_index} arm to {result.get('arm')}"
    except Exception as e:
        logger.error(f"Error setting track arm: {str(e)}")
        return f"Error setting track arm: {str(e)}"


@mcp.tool()
def set_track_mute(ctx: Context, track_index: int, mute: bool) -> str:
    """Mute or unmute a track."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_mute", {"track_index": track_index, "mute": mute})
        return f"Set track {track_index} mute to {result.get('mute')}"
    except Exception as e:
        logger.error(f"Error setting track mute: {str(e)}")
        return f"Error setting track mute: {str(e)}"


@mcp.tool()
def set_track_solo(ctx: Context, track_index: int, solo: bool) -> str:
    """Solo or unsolo a track."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_solo", {"track_index": track_index, "solo": solo})
        return f"Set track {track_index} solo to {result.get('solo')}"
    except Exception as e:
        logger.error(f"Error setting track solo: {str(e)}")
        return f"Error setting track solo: {str(e)}"


@mcp.tool()
def delete_track(ctx: Context, track_index: int) -> str:
    """
    Delete a track. NOTE: deleting a track shifts the indices of every track
    after it down by one. When deleting multiple tracks in a batch, delete in
    descending index order to avoid index drift.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_track", {"track_index": track_index})
        return f"Deleted track {track_index}"
    except Exception as e:
        logger.error(f"Error deleting track: {str(e)}")
        return f"Error deleting track: {str(e)}"


@mcp.tool()
def set_master_volume(ctx: Context, volume: float) -> str:
    """
    Set the master track volume.

    Parameters:
    - volume: 0.0 (silent) to 1.0 (max). Default unity is ~0.85.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_master_volume", {"volume": volume})
        return f"Set master volume to {result.get('volume')}"
    except Exception as e:
        logger.error(f"Error setting master volume: {str(e)}")
        return f"Error setting master volume: {str(e)}"


@mcp.tool()
def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter_index: int,
    value: float,
) -> str:
    """
    Set a device parameter on a track using a RAW Live value (not normalized).
    The value is clamped to the parameter's min/max. Use ``get_track_devices``
    to discover the parameter's index, name, and value range.

    Parameters:
    - track_index: which track the device is on
    - device_index: position of the device in the track's device chain (0-based)
    - parameter_index: position of the parameter in the device (0-based; index 0
      is usually the on/off toggle)
    - value: raw Live value, e.g. 1000.0 for a filter cutoff in Hz
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_parameter", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "value": value,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"


@mcp.tool()
def create_scene(ctx: Context, index: int = -1) -> str:
    """Create a new scene at the given index (-1 = end of list)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_scene", {"index": index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating scene: {str(e)}")
        return f"Error creating scene: {str(e)}"


@mcp.tool()
def set_scene_name(ctx: Context, scene_index: int, name: str) -> str:
    """Set a scene's name."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scene_name", {"scene_index": scene_index, "name": name})
        return f"Set scene {scene_index} name to '{result.get('name')}'"
    except Exception as e:
        logger.error(f"Error setting scene name: {str(e)}")
        return f"Error setting scene name: {str(e)}"


@mcp.tool()
def set_scene_tempo(ctx: Context, scene_index: int, tempo: float) -> str:
    """Set a per-scene tempo. Firing this scene will set the song tempo to this value."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scene_tempo", {"scene_index": scene_index, "tempo": tempo})
        return f"Set scene {scene_index} tempo to {result.get('tempo')}"
    except Exception as e:
        logger.error(f"Error setting scene tempo: {str(e)}")
        return f"Error setting scene tempo: {str(e)}"


# =====================================================================
# Tier 3 — Browser improvements (search_browser, load_instrument_by_name,
# get_track_devices)
# =====================================================================

@mcp.tool()
def search_browser(ctx: Context, query: str, category: str = "all") -> str:
    """
    Search the Ableton browser by name. Walks the browser tree depth-first
    and returns up to 50 matches whose names contain the query (case-insensitive).

    Parameters:
    - query: substring to match (e.g. "808", "Operator", "Reverb")
    - category: "all" | "instruments" | "sounds" | "drums" | "audio_effects" | "midi_effects"

    Returns a list of matches with ``name``, ``uri``, ``path``, and ``is_loadable``.
    Pass the ``uri`` to ``load_browser_item`` to load the result onto a track.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("search_browser", {"query": query, "category": category})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error searching browser: {str(e)}")
        return f"Error searching browser: {str(e)}"


@mcp.tool()
def load_instrument_by_name(
    ctx: Context,
    track_index: int,
    name: str,
    category: str = "instruments",
) -> str:
    """
    Convenience composite: search the browser by name and load the first
    loadable match onto the given track. Equivalent to calling
    ``search_browser`` then ``load_browser_item`` yourself.

    Parameters:
    - track_index: where to load the instrument
    - name: substring of the instrument name (e.g. "Operator", "808 Core")
    - category: which browser category to search; defaults to "instruments"
    """
    try:
        ableton = get_ableton_connection()
        search_result = ableton.send_command("search_browser", {"query": name, "category": category})
        matches = search_result.get("matches", [])
        loadable = [m for m in matches if m.get("is_loadable") and m.get("uri")]
        if not loadable:
            return f"No loadable browser items found matching '{name}' in category '{category}'"
        chosen = loadable[0]
        ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": chosen["uri"],
        })
        return f"Loaded '{chosen['name']}' onto track {track_index} (path: {chosen.get('path', '?')})"
    except Exception as e:
        logger.error(f"Error loading instrument by name: {str(e)}")
        return f"Error loading instrument by name: {str(e)}"


@mcp.tool()
def browse_for_role(ctx: Context, role: str, max_results: int = 15) -> str:
    """
    Walk Ableton's browser for instruments suited to a specific role and return
    quality-ranked candidates.

    Roles:
    - **drums** — searches drum racks and drum kits
    - **bass** — bass instruments (electric, fretless, upright, slap)
    - **lead** — synth leads
    - **keys** — pianos / Rhodes / Wurlis / organs / electric pianos
    - **pad** — pads / atmospheres
    - **brass** — trumpet / sax / horn
    - **guitar** — clean guitar / jazz guitar

    Each item is scored — Instrument Racks (.adg) > Device Presets (.adv) >
    bare devices > raw samples (.wav). One-shot junk and FX-only items are
    filtered out. Results are sorted best-first so ``results[0]`` is the
    smartest pick.

    Use this when you don't know what's in the user's library and want a
    quick menu of options for a given track role.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("browse_for_role", {
            "role": role,
            "max_results": max_results,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error browsing for role: {str(e)}")
        return f"Error browsing for role: {str(e)}"


@mcp.tool()
def load_instrument_for_personality(
    ctx: Context,
    track_index: int,
    personality: str,
    prefer_preset: bool = True,
) -> str:
    """
    Load the best Ableton instrument for the named personality onto a track.

    Each personality has a ``BROWSER_HINTS`` list (e.g. Coltrane → ['tenor sax',
    'saxophone', 'sax', 'brass']). This tool walks those hints in order, runs
    a quality-scored ``search_browser`` for each, and loads the highest-scored
    Instrument Rack / Device Preset across all hints onto the given track.

    The Live API REPLACES the existing instrument when you load another one,
    so this is also a clean way to swap out a placeholder Operator for the
    "right" instrument for a personality.

    Parameters:
    - track_index: target track
    - personality: any key from ``list_personalities``
    - prefer_preset: rank Instrument Racks above raw samples (default True)

    Returns the loaded item's name, path, score, and which hint matched.
    """
    try:
        ableton = get_ableton_connection()
        key = personality.strip().lower().replace(" ", "_")
        if key not in _personalities.PERSONALITIES:
            return f"Unknown personality '{personality}'"
        if key not in _personalities.BROWSER_HINTS:
            return f"No browser hints registered for personality '{personality}'"
        hints = _personalities.BROWSER_HINTS[key]
        profile = _personalities.PERSONALITIES[key]

        # Try every hint, collect every loadable result. Track HINT INDEX so
        # we can prefer earlier hints when scores tie — Coltrane's "tenor sax"
        # (index 0) should beat "wind" (index 4) for Alto Sax even if both
        # candidates score 1.00.
        candidates = []
        tried = []
        for hint_index, hint in enumerate(hints):
            try:
                res = ableton.send_command("search_browser", {
                    "query": hint,
                    "category": "all",
                    "prefer_preset": prefer_preset,
                    "max_results": 5,
                })
                tried.append({"hint": hint, "matches": res.get("match_count", 0)})
                for m in res.get("matches", []):
                    if m.get("is_loadable") and m.get("uri"):
                        candidates.append({
                            "hint": hint,
                            "hint_index": hint_index,
                            "name": m["name"],
                            "uri": m["uri"],
                            "path": m.get("path", ""),
                            "score": m.get("score", 0),
                        })
            except Exception as e:
                tried.append({"hint": hint, "error": str(e)})

        if not candidates:
            return json.dumps({
                "personality": profile["name"],
                "loaded": False,
                "reason": "No loadable browser items found for any of the hints",
                "hints_tried": tried,
            }, indent=2)

        # Sort: highest score first, then earliest hint, then alphabetic name.
        # Negate score so the natural ascending sort puts the best first.
        candidates.sort(key=lambda c: (-c["score"], c["hint_index"], c["name"]))
        chosen = candidates[0]

        ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": chosen["uri"],
        })

        return json.dumps({
            "personality": profile["name"],
            "loaded": True,
            "name": chosen["name"],
            "path": chosen["path"],
            "score": chosen["score"],
            "matched_hint": chosen["hint"],
            "alternatives": [
                {"name": c["name"], "score": c["score"], "hint": c["hint"]}
                for c in candidates[1:5]
            ],
        }, indent=2)
    except Exception as e:
        logger.error(f"Error loading instrument for personality: {str(e)}")
        return f"Error loading instrument for personality: {str(e)}"


@mcp.tool()
def get_track_devices(ctx: Context, track_index: int) -> str:
    """
    List the devices loaded on a track, including each device's parameters
    with their current value, min, and max. Use this to discover parameter
    indices and ranges before calling ``set_device_parameter``.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_devices", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track devices: {str(e)}")
        return f"Error getting track devices: {str(e)}"


# =====================================================================
# Tier 1 — Composite "song scaffold" tools (built on send_batch)
# =====================================================================

@mcp.tool()
def create_track(
    ctx: Context,
    type: str = "midi",
    name: Optional[str] = None,
    instrument_uri: Optional[str] = None,
    volume: Optional[float] = None,
    pan: Optional[float] = None,
    index: int = -1,
) -> str:
    """
    Create a track with optional name, instrument, volume, and pan in a
    single round-trip.

    Parameters:
    - type: "midi" or "audio"
    - name: optional track name
    - instrument_uri: optional browser URI to load (use ``search_browser`` first)
    - volume: optional 0.0-1.0 mixer volume
    - pan: optional -1.0 to 1.0 panning
    - index: insert position (-1 = end)
    """
    try:
        if type not in ("midi", "audio"):
            return "type must be 'midi' or 'audio'"
        ableton = get_ableton_connection()
        commands: List[Dict[str, Any]] = []
        create_cmd = "create_midi_track" if type == "midi" else "create_audio_track"
        commands.append({"type": create_cmd, "params": {"index": index}})
        # The newly created track is at the end of the track list (or at
        # `index` if non-negative). We don't know the resolved index yet, so
        # we let the remote run the batch and then call get_session_info
        # afterward only if needed. For setup ops we use the post-creation
        # track count to compute the index.
        # Simpler: use a session-info read inside the batch is unsafe (no
        # variable binding), so we do create + post-batch follow-ups here.
        result = ableton.send_batch(commands)
        if result.get("failed_at") is not None:
            return json.dumps(result, indent=2)
        created = result["results"][0]["result"]
        new_index = created.get("index")
        # Now apply the optional follow-ups in a second batch
        followups: List[Dict[str, Any]] = []
        if name is not None:
            followups.append({"type": "set_track_name", "params": {"track_index": new_index, "name": name}})
        if instrument_uri is not None:
            followups.append({"type": "load_browser_item", "params": {"track_index": new_index, "item_uri": instrument_uri}})
        if volume is not None:
            followups.append({"type": "set_track_volume", "params": {"track_index": new_index, "volume": volume}})
        if pan is not None:
            followups.append({"type": "set_track_pan", "params": {"track_index": new_index, "pan": pan}})
        if followups:
            follow_result = ableton.send_batch(followups)
            return json.dumps({"created": created, "followups": follow_result}, indent=2)
        return json.dumps({"created": created}, indent=2)
    except Exception as e:
        logger.error(f"Error creating track: {str(e)}")
        return f"Error creating track: {str(e)}"


@mcp.tool()
def create_clip_with_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    length: float,
    notes: List[Dict[str, Any]],
    name: Optional[str] = None,
) -> str:
    """
    Create a MIDI clip and populate it with notes in a single batched call.

    Parameters:
    - track_index, clip_index: where to put the clip
    - length: clip length in beats
    - notes: list of note dicts {pitch, start_time, duration, velocity?, mute?}
    - name: optional clip name
    """
    try:
        ableton = get_ableton_connection()
        commands: List[Dict[str, Any]] = [
            {"type": "create_clip", "params": {
                "track_index": track_index, "clip_index": clip_index, "length": length}},
            {"type": "add_notes_to_clip", "params": {
                "track_index": track_index, "clip_index": clip_index, "notes": notes}},
        ]
        if name is not None:
            commands.append({"type": "set_clip_name", "params": {
                "track_index": track_index, "clip_index": clip_index, "name": name}})
        result = ableton.send_batch(commands)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error in create_clip_with_notes: {str(e)}")
        return f"Error in create_clip_with_notes: {str(e)}"


@mcp.tool()
def duplicate_clip(
    ctx: Context,
    src_track: int,
    src_slot: int,
    dst_track: int,
    dst_slot: int,
) -> str:
    """
    Duplicate a MIDI clip to any other track + slot. Unlike the upstream
    ``duplicate_clip_to``, this works across tracks. Both tracks must be
    MIDI tracks; the destination slot must be empty.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_clip_cross_track", {
            "src_track": src_track,
            "src_slot": src_slot,
            "dst_track": dst_track,
            "dst_slot": dst_slot,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error duplicating clip: {str(e)}")
        return f"Error duplicating clip: {str(e)}"


@mcp.tool()
def setup_session(
    ctx: Context,
    tempo: Optional[float] = None,
    time_signature: Optional[List[int]] = None,
    tracks: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Bootstrap an Ableton session in (effectively) one round-trip: set tempo,
    set time signature, and create a list of tracks with optional names,
    instruments, volume, and pan.

    Parameters:
    - tempo: BPM (e.g. 120.0)
    - time_signature: [numerator, denominator], e.g. [4, 4] or [6, 8]
    - tracks: list of dicts. Each entry may contain:
        - type: "midi" or "audio" (default "midi")
        - name: optional track name
        - instrument_uri: optional browser URI (load via ``search_browser`` first)
        - volume: optional 0.0-1.0
        - pan: optional -1.0 to 1.0

    Tracks are created in order at the END of the existing track list.
    Returns a JSON summary of every step.
    """
    try:
        ableton = get_ableton_connection()
        # Step 1: get current track count so we know the indices of the
        # tracks we are about to create.
        session = ableton.send_command("get_session_info")
        starting_track_count = int(session.get("track_count", 0))

        # Step 2: build the bootstrap batch (tempo + time sig + create tracks)
        bootstrap: List[Dict[str, Any]] = []
        if tempo is not None:
            bootstrap.append({"type": "set_tempo", "params": {"tempo": tempo}})
        if time_signature is not None:
            if not isinstance(time_signature, (list, tuple)) or len(time_signature) != 2:
                return "time_signature must be a [numerator, denominator] pair"
            bootstrap.append({"type": "set_time_signature", "params": {
                "numerator": time_signature[0], "denominator": time_signature[1]}})
        track_specs = tracks or []
        for spec in track_specs:
            t = spec.get("type", "midi")
            if t not in ("midi", "audio"):
                return f"track type must be 'midi' or 'audio', got '{t}'"
            create_cmd = "create_midi_track" if t == "midi" else "create_audio_track"
            bootstrap.append({"type": create_cmd, "params": {"index": -1}})
        bootstrap_result = ableton.send_batch(bootstrap)
        if bootstrap_result.get("failed_at") is not None:
            return json.dumps({"phase": "bootstrap", "result": bootstrap_result}, indent=2)

        # Step 3: build the per-track follow-up batch (name, instrument, volume, pan)
        followups: List[Dict[str, Any]] = []
        for offset, spec in enumerate(track_specs):
            track_index = starting_track_count + offset
            if "name" in spec and spec["name"] is not None:
                followups.append({"type": "set_track_name", "params": {
                    "track_index": track_index, "name": spec["name"]}})
            if spec.get("instrument_uri"):
                followups.append({"type": "load_browser_item", "params": {
                    "track_index": track_index, "item_uri": spec["instrument_uri"]}})
            if spec.get("volume") is not None:
                followups.append({"type": "set_track_volume", "params": {
                    "track_index": track_index, "volume": spec["volume"]}})
            if spec.get("pan") is not None:
                followups.append({"type": "set_track_pan", "params": {
                    "track_index": track_index, "pan": spec["pan"]}})
        followup_result = None
        if followups:
            followup_result = ableton.send_batch(followups)

        return json.dumps({
            "starting_track_count": starting_track_count,
            "tracks_created": len(track_specs),
            "bootstrap": bootstrap_result,
            "followups": followup_result,
        }, indent=2)
    except Exception as e:
        logger.error(f"Error in setup_session: {str(e)}")
        return f"Error in setup_session: {str(e)}"


# =====================================================================
# Tier 5 — Arrangement view (BETA — capability-probed; some operations may
# be unsupported on older Live versions and will return a structured error)
# =====================================================================

@mcp.tool()
def get_arrangement_info(ctx: Context) -> str:
    """
    BETA: Report arrangement-view state — capabilities, song length, loop
    region, locators (cue points), and per-track arrangement clips.

    The ``capabilities`` field tells you which BETA operations this Live
    version supports. ``can_duplicate_to_arrangement`` is the most important
    one — it gates ``add_clip_to_arrangement`` and
    ``bounce_session_to_arrangement``.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting arrangement info: {str(e)}")
        return f"Error getting arrangement info: {str(e)}"


@mcp.tool()
def add_clip_to_arrangement(
    ctx: Context,
    track_index: int,
    clip_slot_index: int,
    arrangement_time: float,
) -> str:
    """
    BETA: Copy a session clip onto the arrangement timeline at the given
    time (in beats). Requires a Live version that exposes
    ``Track.duplicate_clip_to_arrangement``. Use ``get_arrangement_info``
    first to confirm support.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_clip_to_arrangement", {
            "track_index": track_index,
            "clip_slot_index": clip_slot_index,
            "arrangement_time": arrangement_time,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error adding clip to arrangement: {str(e)}")
        return f"Error adding clip to arrangement: {str(e)}"


@mcp.tool()
def set_arrangement_loop(ctx: Context, start: float, end: float, loop_on: bool = True) -> str:
    """
    Set the arrangement loop region (in beats) and whether the loop is
    enabled. Stable across Live 11+.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_arrangement_loop", {
            "start": start, "end": end, "loop_on": loop_on,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting arrangement loop: {str(e)}")
        return f"Error setting arrangement loop: {str(e)}"


@mcp.tool()
def add_arrangement_locator(ctx: Context, time: float, name: str = "") -> str:
    """
    Add a named locator (cue point) at the given arrangement time. Useful
    for marking verse / chorus / bridge boundaries.

    If a locator already exists at that exact time, this only renames it.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_arrangement_locator", {"time": time, "name": name})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error adding arrangement locator: {str(e)}")
        return f"Error adding arrangement locator: {str(e)}"


@mcp.tool()
def bounce_session_to_arrangement(
    ctx: Context,
    scene_order: List[int],
    bar_length: float = 4.0,
) -> str:
    """
    BETA: Render a sequence of scenes onto the arrangement timeline. For
    each scene in ``scene_order`` (in order), every clip in that scene's
    row is dropped onto the arrangement at the running time cursor. The
    cursor advances by ``bar_length`` beats after each scene.

    This is the closest thing to a one-call "session sketch → arrangement"
    flow. Requires a Live version that supports
    ``Track.duplicate_clip_to_arrangement``.

    Parameters:
    - scene_order: list of scene indices in playback order, e.g. [0, 0, 1, 2, 1, 3]
    - bar_length: how many beats each scene occupies on the timeline (default 4)
    """
    try:
        ableton = get_ableton_connection()
        # Confirm capability + collect track info
        info = ableton.send_command("get_arrangement_info")
        if not info.get("capabilities", {}).get("can_duplicate_to_arrangement"):
            return json.dumps({
                "supported": False,
                "reason": "This Live version does not expose Track.duplicate_clip_to_arrangement",
            }, indent=2)
        # Discover which tracks have clips at each scene index
        session = ableton.send_command("get_session_info")
        track_count = int(session.get("track_count", 0))
        # We need each track's clip slots to know which slots are non-empty.
        # Use get_track_info per track (cheap; pure read).
        track_slot_status: List[List[bool]] = []
        for ti in range(track_count):
            ti_info = ableton.send_command("get_track_info", {"track_index": ti})
            slots = ti_info.get("clip_slots", [])
            track_slot_status.append([bool(s.get("has_clip", False)) for s in slots])

        # Build the batch
        commands: List[Dict[str, Any]] = []
        cursor = 0.0
        scenes_placed = 0
        clips_placed = 0
        for scene_idx in scene_order:
            for ti in range(track_count):
                if scene_idx < len(track_slot_status[ti]) and track_slot_status[ti][scene_idx]:
                    commands.append({"type": "add_clip_to_arrangement", "params": {
                        "track_index": ti,
                        "clip_slot_index": scene_idx,
                        "arrangement_time": cursor,
                    }})
                    clips_placed += 1
            cursor += float(bar_length)
            scenes_placed += 1
        if not commands:
            return "No clips found to bounce — scene_order references empty rows"
        batch_result = ableton.send_batch(commands)
        return json.dumps({
            "supported": True,
            "scenes_placed": scenes_placed,
            "clips_placed": clips_placed,
            "total_arrangement_length": cursor,
            "batch": batch_result,
        }, indent=2)
    except Exception as e:
        logger.error(f"Error bouncing session to arrangement: {str(e)}")
        return f"Error bouncing session to arrangement: {str(e)}"


# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()