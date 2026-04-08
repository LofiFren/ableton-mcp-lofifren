# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import socket
import json
import threading
import time
import traceback

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()

        # Build command dispatch tables (one entry per supported command)
        self._build_dispatch_tables()

        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        
        # Stop the server
        if self.server:
            try:
                self.server.close()
            except:
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client"""
        self.log_message("Client handler started")
        client.settimeout(None)  # No timeout for client socket
        buffer = ''  # Changed from b'' to '' for Python 2
        
        try:
            while self.running:
                try:
                    # Receive data
                    data = client.recv(8192)
                    
                    if not data:
                        # Client disconnected
                        self.log_message("Client disconnected")
                        break
                    
                    # Accumulate data in buffer with explicit encoding/decoding
                    try:
                        # Python 3: data is bytes, decode to string
                        buffer += data.decode('utf-8')
                    except AttributeError:
                        # Python 2: data is already string
                        buffer += data
                    
                    try:
                        # Try to parse command from buffer
                        command = json.loads(buffer)  # Removed decode('utf-8')
                        buffer = ''  # Clear buffer after successful parse
                        
                        self.log_message("Received command: " + str(command.get("type", "unknown")))
                        
                        # Process the command and get response
                        response = self._process_command(command)
                        
                        # Send the response with explicit encoding
                        try:
                            # Python 3: encode string to bytes
                            client.sendall(json.dumps(response).encode('utf-8'))
                        except AttributeError:
                            # Python 2: string is already bytes
                            client.sendall(json.dumps(response))
                    except ValueError:
                        # Incomplete data, wait for more
                        continue
                        
                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    
                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    try:
                        # Python 3: encode string to bytes
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except AttributeError:
                        # Python 2: string is already bytes
                        client.sendall(json.dumps(error_response))
                    except:
                        # If we can't send the error, the connection is probably dead
                        break
                    
                    # For serious errors, break the loop
                    if not isinstance(e, ValueError):
                        break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except:
                pass
            self.log_message("Client handler stopped")
    
    def _build_dispatch_tables(self):
        """Build the read-only and modifying command dispatch tables.

        Each entry maps a command name to a callable taking the params dict
        and returning a result dict. Adding a new command means adding one
        line here plus the corresponding ``_handler`` method.
        """
        self._readonly_commands = {
            "get_session_info":          lambda p: self._get_session_info(),
            "get_track_info":            lambda p: self._get_track_info(p.get("track_index", 0)),
            "get_clip_notes":            lambda p: self._get_clip_notes(p.get("track_index", 0), p.get("clip_index", 0)),
            "get_browser_item":          lambda p: self._get_browser_item(p.get("uri", None), p.get("path", None)),
            "get_browser_tree":          lambda p: self.get_browser_tree(p.get("category_type", "all")),
            "get_browser_items_at_path": lambda p: self.get_browser_items_at_path(p.get("path", "")),
            "search_browser":            lambda p: self._search_browser(p.get("query", ""), p.get("category", "all"), p.get("prefer_preset", True), p.get("max_results", 50)),
            "browse_for_role":           lambda p: self._browse_for_role(p.get("role", "lead"), p.get("max_results", 15)),
            "get_track_devices":         lambda p: self._get_track_devices(p.get("track_index", 0)),
            # Tier 5 arrangement view (read-only ones)
            "arrangement_capabilities":  lambda p: self._arrangement_capabilities(),
            "get_arrangement_info":      lambda p: self._get_arrangement_info(),
        }
        self._modifying_commands = {
            "create_midi_track":      lambda p: self._create_midi_track(p.get("index", -1)),
            "create_audio_track":     lambda p: self._create_audio_track(p.get("index", -1)),
            "set_track_name":         lambda p: self._set_track_name(p.get("track_index", 0), p.get("name", "")),
            "create_clip":            lambda p: self._create_clip(p.get("track_index", 0), p.get("clip_index", 0), p.get("length", 4.0)),
            "add_notes_to_clip":      lambda p: self._add_notes_to_clip(p.get("track_index", 0), p.get("clip_index", 0), p.get("notes", [])),
            "set_clip_name":          lambda p: self._set_clip_name(p.get("track_index", 0), p.get("clip_index", 0), p.get("name", "")),
            "set_tempo":              lambda p: self._set_tempo(p.get("tempo", 120.0)),
            "fire_clip":              lambda p: self._fire_clip(p.get("track_index", 0), p.get("clip_index", 0)),
            "stop_clip":              lambda p: self._stop_clip(p.get("track_index", 0), p.get("clip_index", 0)),
            "start_playback":         lambda p: self._start_playback(),
            "stop_playback":          lambda p: self._stop_playback(),
            "load_browser_item":      lambda p: self._load_browser_item(p.get("track_index", 0), p.get("item_uri", "")),
            "remove_notes_from_clip": lambda p: self._remove_notes_from_clip(
                p.get("track_index", 0), p.get("clip_index", 0),
                p.get("from_time", 0.0), p.get("from_pitch", 0),
                p.get("time_span", 99999.0), p.get("pitch_span", 128)),
            "delete_clip":            lambda p: self._delete_clip(p.get("track_index", 0), p.get("clip_index", 0)),
            "duplicate_clip_to":      lambda p: self._duplicate_clip_to(p.get("track_index", 0), p.get("clip_index", 0), p.get("target_clip_index", 0)),
            "set_track_volume":       lambda p: self._set_track_volume(p.get("track_index", 0), p.get("volume", 0.85)),
            "set_track_pan":          lambda p: self._set_track_pan(p.get("track_index", 0), p.get("pan", 0.0)),
            "set_track_send":         lambda p: self._set_track_send(p.get("track_index", 0), p.get("send_index", 0), p.get("value", 0.0)),
            "fire_scene":             lambda p: self._fire_scene(p.get("scene_index", 0)),
            "undo":                   lambda p: self._undo(),
            "batch_commands":         lambda p: self._batch_commands(p.get("commands", [])),
            # Tier 2 primitives
            "set_time_signature":     lambda p: self._set_time_signature(p.get("numerator", 4), p.get("denominator", 4)),
            "set_clip_loop":          lambda p: self._set_clip_loop(p.get("track_index", 0), p.get("clip_index", 0), p.get("loop_start", 0.0), p.get("loop_end", 4.0), p.get("loop_on", True)),
            "set_clip_length":        lambda p: self._set_clip_length(p.get("track_index", 0), p.get("clip_index", 0), p.get("length", 4.0)),
            "set_track_arm":          lambda p: self._set_track_arm(p.get("track_index", 0), p.get("arm", False)),
            "set_track_mute":         lambda p: self._set_track_mute(p.get("track_index", 0), p.get("mute", False)),
            "set_track_solo":         lambda p: self._set_track_solo(p.get("track_index", 0), p.get("solo", False)),
            "delete_track":           lambda p: self._delete_track(p.get("track_index", 0)),
            "set_master_volume":      lambda p: self._set_master_volume(p.get("volume", 0.85)),
            "set_device_parameter":   lambda p: self._set_device_parameter(p.get("track_index", 0), p.get("device_index", 0), p.get("parameter_index", 0), p.get("value", 0.0)),
            "create_scene":           lambda p: self._create_scene(p.get("index", -1)),
            "set_scene_name":         lambda p: self._set_scene_name(p.get("scene_index", 0), p.get("name", "")),
            "set_scene_tempo":        lambda p: self._set_scene_tempo(p.get("scene_index", 0), p.get("tempo", 120.0)),
            # Tier 1 cross-track duplicate
            "duplicate_clip_cross_track": lambda p: self._duplicate_clip_cross_track(
                p.get("src_track", 0), p.get("src_slot", 0),
                p.get("dst_track", 0), p.get("dst_slot", 0)),
            # Tier 5 arrangement view (modifying ones)
            "add_clip_to_arrangement":   lambda p: self._add_clip_to_arrangement(
                p.get("track_index", 0), p.get("clip_slot_index", 0), p.get("arrangement_time", 0.0)),
            "set_arrangement_loop":      lambda p: self._set_arrangement_loop(
                p.get("start", 0.0), p.get("end", 4.0), p.get("loop_on", True)),
        }
        # Async modifying commands chain main-thread closures via schedule_message
        # so Live can commit state between operations. Each handler takes
        # (params, response_queue, cancelled) and is responsible for putting a
        # result/error into the queue from its FINAL closure. Used for
        # operations that depend on Live's main thread idling between writes
        # — e.g. Song.current_song_time only commits after the closure returns.
        self._async_modifying_commands = {
            "add_arrangement_locator":         self._add_arrangement_locator_async,
            "clear_all_arrangement_locators":  self._clear_all_arrangement_locators_async,
        }

    def _process_command(self, command):
        """Process a command from the client and return a response"""
        command_type = command.get("type", "")
        params = command.get("params", {})

        response = {"status": "success", "result": {}}

        try:
            if command_type in self._readonly_commands:
                # Read-only commands run directly on the socket thread
                response["result"] = self._readonly_commands[command_type](params)
            elif command_type in self._modifying_commands:
                # Modifying commands must run on Live's main thread
                response["result"] = self._run_on_main_thread(command_type, params)
            elif command_type in self._async_modifying_commands:
                # Async commands chain main-thread closures so Live can commit
                # internal state (like current_song_time) between operations.
                response["result"] = self._run_async_on_main_thread(command_type, params)
            else:
                response["status"] = "error"
                response["message"] = "Unknown command: " + command_type
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)

        return response

    def _run_on_main_thread(self, command_type, params):
        """Schedule a modifying command on Live's main thread and wait for the result.

        Raises Exception on timeout or handler failure; the caller (``_process_command``)
        converts those into the JSON error response.
        """
        handler = self._modifying_commands[command_type]
        response_queue = queue.Queue()
        # Cancellation flag: if the wait times out, prevent late execution
        # of destructive operations that haven't started yet
        cancelled = [False]

        def main_thread_task():
            try:
                if cancelled[0]:
                    self.log_message("Skipping cancelled command: " + command_type)
                    return
                result = handler(params)
                response_queue.put({"status": "success", "result": result})
            except Exception as e:
                self.log_message("Error in main thread task: " + str(e))
                self.log_message(traceback.format_exc())
                response_queue.put({"status": "error", "message": str(e)})

        # Schedule the task to run on the main thread
        try:
            self.schedule_message(0, main_thread_task)
        except AssertionError:
            # Already on the main thread; execute directly
            main_thread_task()

        # Wait for the response with a timeout
        try:
            task_response = response_queue.get(timeout=10.0)
        except queue.Empty:
            cancelled[0] = True
            self.log_message("Timeout for command: " + command_type + " - marking cancelled")
            raise Exception("Timeout waiting for operation to complete. The operation was cancelled to prevent unintended side effects.")

        if task_response.get("status") == "error":
            raise Exception(task_response.get("message", "Unknown error"))

        return task_response.get("result", {})

    def _run_async_on_main_thread(self, command_type, params):
        """Schedule an async modifying command and wait for the result.

        Async commands chain main-thread closures via ``schedule_message`` so
        Live can commit internal state between operations. The handler takes
        ``(params, response_queue, cancelled)`` and is responsible for putting
        a ``{"status": "success"|"error", ...}`` dict into the queue from its
        FINAL closure. We block on the queue here on the SOCKET thread (NOT
        the main thread), so blocking is safe and Live's main loop continues
        to process its scheduled callbacks.
        """
        handler = self._async_modifying_commands[command_type]
        response_queue = queue.Queue()
        cancelled = [False]

        def kickoff():
            try:
                if cancelled[0]:
                    return
                handler(params, response_queue, cancelled)
            except Exception as e:
                self.log_message("Error kicking off async task: " + str(e))
                self.log_message(traceback.format_exc())
                response_queue.put({"status": "error", "message": str(e)})

        try:
            self.schedule_message(0, kickoff)
        except AssertionError:
            kickoff()

        # Async chains can take many ticks (especially clear_all_arrangement_locators
        # which iterates each cue). Give them more time than the sync runner.
        try:
            task_response = response_queue.get(timeout=30.0)
        except queue.Empty:
            cancelled[0] = True
            self.log_message("Async timeout for command: " + command_type + " - marking cancelled")
            raise Exception("Timeout waiting for async operation to complete.")

        if task_response.get("status") == "error":
            raise Exception(task_response.get("message", "Unknown error"))

        return task_response.get("result", {})

    # Command implementations
    
    def _get_session_info(self):
        """Get information about the current session"""
        try:
            scenes = self._song.scenes
            scene_names = []
            for scene in scenes:
                try:
                    scene_names.append(scene.name)
                except Exception:
                    scene_names.append("")
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "scene_count": len(scenes),
                "scene_names": scene_names,
                "is_playing": self._song.is_playing,
                "current_song_time": self._song.current_song_time,
                "arrangement_length": getattr(self._song, "last_event_time", 0.0),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Get clip slots
            clip_slots = []
            for slot_index, slot in enumerate(track.clip_slots):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "mute": track.mute,
                "solo": track.solo,
                "arm": track.arm,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "clip_slots": clip_slots,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise
    
    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise
    
    
    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            # Set the name
            track = self._song.tracks[track_index]
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise
    
    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    def _add_notes_to_clip(self, track_index, clip_index, notes):
        """Add MIDI notes to a clip.

        If any of the supplied notes would extend past the clip's current
        ``end_marker``, the clip is automatically resized to fit. (Upstream
        behavior was to silently truncate notes — this fork extends instead.)
        """
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            # Convert note data to Live's format
            live_notes = []
            max_end = 0.0
            for note in notes:
                pitch = note.get("pitch", 60)
                start_time = note.get("start_time", 0.0)
                duration = note.get("duration", 0.25)
                velocity = note.get("velocity", 100)
                mute = note.get("mute", False)

                live_notes.append((pitch, start_time, duration, velocity, mute))
                note_end = float(start_time) + float(duration)
                if note_end > max_end:
                    max_end = note_end

            # Auto-extend the clip end_marker if any note would otherwise be
            # truncated. We compare against end_marker (not length) because
            # length is read-only and end_marker - start_marker == length.
            extended = False
            new_end_marker = None
            try:
                if max_end > clip.length:
                    target_end = clip.start_marker + max_end
                    if clip.loop_end > target_end:
                        # Loop end can't be inside the clip; widen it first
                        pass
                    else:
                        # Make sure loop_end <= end_marker invariant holds
                        if clip.loop_end > target_end:
                            clip.loop_end = target_end
                    clip.end_marker = target_end
                    new_end_marker = clip.end_marker
                    extended = True
            except Exception as ext_err:
                # Don't fail the whole call if extension fails — log and proceed.
                self.log_message("Auto-extend skipped: " + str(ext_err))

            # Add the notes
            clip.set_notes(tuple(live_notes))

            result = {
                "note_count": len(notes),
                "auto_extended": extended,
                "end_marker": new_end_marker if extended else clip.end_marker,
                "length": clip.length,
            }
            return result
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise
    
    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise
    
    def _get_clip_notes(self, track_index, clip_index):
        """Get all notes from a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            # Get all notes from the clip
            # get_notes(from_time, from_pitch, time_span, pitch_span)
            notes_tuple = clip.get_notes(0.0, 0, clip.length, 128)

            notes = []
            for note in notes_tuple:
                notes.append({
                    "pitch": note[0],
                    "start_time": note[1],
                    "duration": note[2],
                    "velocity": note[3],
                    "mute": note[4]
                })

            result = {
                "note_count": len(notes),
                "clip_length": clip.length,
                "notes": notes
            }
            return result
        except Exception as e:
            self.log_message("Error getting clip notes: " + str(e))
            raise

    def _remove_notes_from_clip(self, track_index, clip_index, from_time, from_pitch, time_span, pitch_span):
        """Remove notes from a clip within the specified range"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            # Remove notes in the specified range
            clip.remove_notes(from_time, from_pitch, time_span, pitch_span)

            result = {
                "removed": True,
                "from_time": from_time,
                "from_pitch": from_pitch,
                "time_span": time_span,
                "pitch_span": pitch_span
            }
            return result
        except Exception as e:
            self.log_message("Error removing notes from clip: " + str(e))
            raise

    def _delete_clip(self, track_index, clip_index):
        """Delete a clip from a clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip_slot.delete_clip()

            result = {
                "deleted": True
            }
            return result
        except Exception as e:
            self.log_message("Error deleting clip: " + str(e))
            raise

    def _duplicate_clip_to(self, track_index, clip_index, target_clip_index):
        """Duplicate a clip to another clip slot on the same track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Source clip index out of range")

            if target_clip_index < 0 or target_clip_index >= len(track.clip_slots):
                raise IndexError("Target clip index out of range")

            source_slot = track.clip_slots[clip_index]
            target_slot = track.clip_slots[target_clip_index]

            if not source_slot.has_clip:
                raise Exception("No clip in source slot")

            if target_slot.has_clip:
                raise Exception("Target slot already has a clip")

            source_slot.duplicate_clip_to(target_slot)

            result = {
                "duplicated": True,
                "source_slot": clip_index,
                "target_slot": target_clip_index
            }
            return result
        except Exception as e:
            self.log_message("Error duplicating clip: " + str(e))
            raise

    def _set_track_volume(self, track_index, volume):
        """Set the volume of a track (0.0 to 1.0)"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            track.mixer_device.volume.value = max(0.0, min(1.0, volume))

            result = {
                "volume": track.mixer_device.volume.value
            }
            return result
        except Exception as e:
            self.log_message("Error setting track volume: " + str(e))
            raise

    def _set_track_pan(self, track_index, pan):
        """Set the panning of a track (-1.0 to 1.0)"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            track.mixer_device.panning.value = max(-1.0, min(1.0, pan))

            result = {
                "panning": track.mixer_device.panning.value
            }
            return result
        except Exception as e:
            self.log_message("Error setting track panning: " + str(e))
            raise

    def _set_track_send(self, track_index, send_index, value):
        """Set a send amount on a track (0.0 to 1.0)"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            sends = track.mixer_device.sends

            if send_index < 0 or send_index >= len(sends):
                raise IndexError("Send index out of range (track has {0} sends)".format(len(sends)))

            sends[send_index].value = max(0.0, min(1.0, value))

            result = {
                "send_index": send_index,
                "value": sends[send_index].value
            }
            return result
        except Exception as e:
            self.log_message("Error setting track send: " + str(e))
            raise

    def _fire_scene(self, scene_index):
        """Fire (launch) a scene, triggering all clips in that row"""
        try:
            scenes = self._song.scenes
            if scene_index < 0 or scene_index >= len(scenes):
                raise IndexError("Scene index out of range (session has {0} scenes)".format(len(scenes)))

            scenes[scene_index].fire()

            result = {
                "fired": True,
                "scene_index": scene_index,
                "scene_name": scenes[scene_index].name
            }
            return result
        except Exception as e:
            self.log_message("Error firing scene: " + str(e))
            raise

    def _create_audio_track(self, index):
        """Create a new audio track at the specified index"""
        try:
            self._song.create_audio_track(index)

            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]

            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating audio track: " + str(e))
            raise

    def _undo(self):
        """Undo the last action"""
        try:
            self._song.undo()

            result = {
                "undone": True
            }
            return result
        except Exception as e:
            self.log_message("Error undoing: " + str(e))
            raise

    def _batch_commands(self, commands):
        """Execute a list of commands sequentially on the main thread.

        Stops on the first failure and returns partial results. Each batch
        element is ``{"type": str, "params": dict}``. Because the whole batch
        runs inside the single main-thread closure scheduled by
        ``_run_on_main_thread``, the entire sequence is atomic from Live's
        perspective and a single ``undo`` will revert all of it.
        """
        results = []
        failed_at = None
        error_message = None
        for index, cmd in enumerate(commands):
            cmd_type = cmd.get("type", "")
            cmd_params = cmd.get("params", {})
            try:
                if cmd_type in self._modifying_commands:
                    handler = self._modifying_commands[cmd_type]
                elif cmd_type in self._readonly_commands:
                    handler = self._readonly_commands[cmd_type]
                elif cmd_type == "batch_commands":
                    raise Exception("Cannot nest batch_commands inside a batch")
                else:
                    raise Exception("Unknown command in batch: " + cmd_type)
                result = handler(cmd_params)
                results.append({"status": "success", "result": result})
            except Exception as e:
                self.log_message("Batch command '{0}' failed at index {1}: {2}".format(
                    cmd_type, index, str(e)))
                self.log_message(traceback.format_exc())
                results.append({"status": "error", "message": str(e)})
                failed_at = index
                error_message = str(e)
                break
        return {
            "results": results,
            "executed": len(results),
            "total": len(commands),
            "failed_at": failed_at,
            "error": error_message,
        }

    # ----- Tier 2 primitives -----

    def _set_time_signature(self, numerator, denominator):
        """Set the song's time signature."""
        try:
            self._song.signature_numerator = int(numerator)
            self._song.signature_denominator = int(denominator)
            return {
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
            }
        except Exception as e:
            self.log_message("Error setting time signature: " + str(e))
            raise

    def _set_clip_loop(self, track_index, clip_index, loop_start, loop_end, loop_on):
        """Set a clip's loop region and loop on/off."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if loop_end <= loop_start:
                raise ValueError("loop_end must be greater than loop_start")
            # Order matters: end before start can fail Live's invariants, so
            # widen the loop range first if needed.
            if loop_start < clip.loop_start:
                clip.loop_start = float(loop_start)
                clip.loop_end = float(loop_end)
            else:
                clip.loop_end = float(loop_end)
                clip.loop_start = float(loop_start)
            clip.looping = bool(loop_on)
            return {
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
                "looping": clip.looping,
            }
        except Exception as e:
            self.log_message("Error setting clip loop: " + str(e))
            raise

    def _set_clip_length(self, track_index, clip_index, length):
        """Set a clip's length by moving its end_marker."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if length <= 0:
                raise ValueError("length must be positive")
            new_end = clip.start_marker + float(length)
            # Adjust loop_end first if necessary so we don't violate
            # loop_end <= end_marker.
            if clip.loop_end > new_end:
                clip.loop_end = new_end
            clip.end_marker = new_end
            return {"length": clip.length}
        except Exception as e:
            self.log_message("Error setting clip length: " + str(e))
            raise

    def _set_track_arm(self, track_index, arm):
        """Set the arm state of a track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if not track.can_be_armed:
                raise Exception("Track cannot be armed (likely a group track)")
            track.arm = bool(arm)
            return {"arm": track.arm}
        except Exception as e:
            self.log_message("Error setting track arm: " + str(e))
            raise

    def _set_track_mute(self, track_index, mute):
        """Set the mute state of a track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            track.mute = bool(mute)
            return {"mute": track.mute}
        except Exception as e:
            self.log_message("Error setting track mute: " + str(e))
            raise

    def _set_track_solo(self, track_index, solo):
        """Set the solo state of a track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            track.solo = bool(solo)
            return {"solo": track.solo}
        except Exception as e:
            self.log_message("Error setting track solo: " + str(e))
            raise

    def _delete_track(self, track_index):
        """Delete a track. NOTE: deleting a track shifts the indices of all
        subsequent tracks down by one — when batching deletes, delete in
        descending index order."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            self._song.delete_track(track_index)
            return {"deleted": True, "track_index": track_index}
        except Exception as e:
            self.log_message("Error deleting track: " + str(e))
            raise

    def _set_master_volume(self, volume):
        """Set the master track volume (0.0 to 1.0)."""
        try:
            self._song.master_track.mixer_device.volume.value = max(0.0, min(1.0, float(volume)))
            return {"volume": self._song.master_track.mixer_device.volume.value}
        except Exception as e:
            self.log_message("Error setting master volume: " + str(e))
            raise

    def _set_device_parameter(self, track_index, device_index, parameter_index, value):
        """Set a device parameter to a raw Live value, clamped to its min/max.

        Use ``get_track_devices`` to discover the parameter's name and range.
        """
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range (track has {0} devices)".format(len(track.devices)))
            device = track.devices[device_index]
            if parameter_index < 0 or parameter_index >= len(device.parameters):
                raise IndexError("Parameter index out of range (device has {0} parameters)".format(len(device.parameters)))
            param = device.parameters[parameter_index]
            if not param.is_enabled:
                raise Exception("Parameter '{0}' is not enabled".format(param.name))
            clamped = max(param.min, min(param.max, float(value)))
            param.value = clamped
            return {
                "device_name": device.name,
                "parameter_name": param.name,
                "value": param.value,
                "min": param.min,
                "max": param.max,
            }
        except Exception as e:
            self.log_message("Error setting device parameter: " + str(e))
            raise

    def _create_scene(self, index):
        """Create a new scene at the given index (-1 = end)."""
        try:
            self._song.create_scene(index)
            new_scene_index = len(self._song.scenes) - 1 if index == -1 else index
            return {"index": new_scene_index, "name": self._song.scenes[new_scene_index].name}
        except Exception as e:
            self.log_message("Error creating scene: " + str(e))
            raise

    def _set_scene_name(self, scene_index, name):
        """Set the name of a scene."""
        try:
            scenes = self._song.scenes
            if scene_index < 0 or scene_index >= len(scenes):
                raise IndexError("Scene index out of range")
            scenes[scene_index].name = name
            return {"name": scenes[scene_index].name}
        except Exception as e:
            self.log_message("Error setting scene name: " + str(e))
            raise

    def _set_scene_tempo(self, scene_index, tempo):
        """Set the tempo of a scene (per-scene tempo automation)."""
        try:
            scenes = self._song.scenes
            if scene_index < 0 or scene_index >= len(scenes):
                raise IndexError("Scene index out of range")
            scenes[scene_index].tempo = float(tempo)
            return {"tempo": scenes[scene_index].tempo}
        except Exception as e:
            self.log_message("Error setting scene tempo: " + str(e))
            raise

    # ----- Tier 1 cross-track duplicate -----

    def _duplicate_clip_cross_track(self, src_track, src_slot, dst_track, dst_slot):
        """Duplicate a MIDI clip across tracks (the existing duplicate_clip_to
        only works within a single track). Reads source notes/loop/name and
        writes them to a freshly created clip on the target slot. Both tracks
        must be MIDI tracks; the destination slot must be empty."""
        try:
            tracks = self._song.tracks
            if src_track < 0 or src_track >= len(tracks):
                raise IndexError("Source track index out of range")
            if dst_track < 0 or dst_track >= len(tracks):
                raise IndexError("Destination track index out of range")
            src_track_obj = tracks[src_track]
            dst_track_obj = tracks[dst_track]
            if not src_track_obj.has_midi_input:
                raise Exception("Source track is not a MIDI track")
            if not dst_track_obj.has_midi_input:
                raise Exception("Destination track is not a MIDI track")
            if src_slot < 0 or src_slot >= len(src_track_obj.clip_slots):
                raise IndexError("Source clip slot index out of range")
            if dst_slot < 0 or dst_slot >= len(dst_track_obj.clip_slots):
                raise IndexError("Destination clip slot index out of range")
            src_clip_slot = src_track_obj.clip_slots[src_slot]
            dst_clip_slot = dst_track_obj.clip_slots[dst_slot]
            if not src_clip_slot.has_clip:
                raise Exception("No clip in source slot")
            if dst_clip_slot.has_clip:
                raise Exception("Destination slot already has a clip")
            src_clip = src_clip_slot.clip
            src_length = src_clip.length
            src_name = src_clip.name
            src_loop_start = src_clip.loop_start
            src_loop_end = src_clip.loop_end
            src_looping = src_clip.looping
            src_notes = src_clip.get_notes(0.0, 0, src_length, 128)
            # Create the destination clip and copy state
            dst_clip_slot.create_clip(src_length)
            dst_clip = dst_clip_slot.clip
            dst_clip.name = src_name
            if src_notes:
                dst_clip.set_notes(tuple(src_notes))
            if src_loop_end > src_loop_start:
                if src_loop_start < dst_clip.loop_start:
                    dst_clip.loop_start = src_loop_start
                    dst_clip.loop_end = src_loop_end
                else:
                    dst_clip.loop_end = src_loop_end
                    dst_clip.loop_start = src_loop_start
            dst_clip.looping = src_looping
            return {
                "src_track": src_track,
                "src_slot": src_slot,
                "dst_track": dst_track,
                "dst_slot": dst_slot,
                "note_count": len(src_notes),
                "length": dst_clip.length,
                "name": dst_clip.name,
            }
        except Exception as e:
            self.log_message("Error duplicating clip across tracks: " + str(e))
            raise

    # ----- Tier 3 browser additions -----

    def _score_browser_item(self, name, path, is_loadable):
        """Quality score in [0,1] for a browser item.

        Higher is better. Used to rank search results so an Instrument Rack
        (.adg) like 'OP 808 Kit.adg' beats a single sample (.wav) like
        'Cowbell 808 DMX.wav' when both match the query 'drums 808'. Pure
        Python, no Live API access — safe to call from the read path.
        """
        if not is_loadable:
            return 0.0
        score = 0.5  # baseline
        n = (name or "").lower()
        p = (path or "").lower()

        # File-type boosts (Live presets > raw samples)
        if n.endswith(".adg"):
            score += 0.40   # Instrument / Drum Rack — curated
        elif n.endswith(".adv"):
            score += 0.30   # Device Preset — Ableton-tuned
        elif n.endswith(".amxd"):
            score += 0.20   # Max for Live device
        elif n.endswith(".wav") or n.endswith(".aif") or n.endswith(".aiff"):
            score -= 0.40   # Raw sample — gets wrapped in Simpler, often a one-shot

        # Bare instrument devices (no extension) like 'Operator', 'Wavetable'
        # are full instruments — slightly above baseline.
        if "." not in n:
            score += 0.05

        # Path hints: presets and kits are usually curated
        for hint in ("preset", "kit", "patch", "rack", "synth"):
            if hint in p:
                score += 0.05
                break

        # Penalize obviously single-element samples / FX-only items
        junk_words = (
            "hit", "one shot", "oneshot", "one-shot",
            "crash", "ride hit", "kick hit", "snare hit", "hat hit",
            "fx", "effect", "noise", "riser", "impact", "downer",
            "vox", "vocal", "atmo", "swoosh", "whoosh", "stab one",
        )
        for w in junk_words:
            if w in n or w in p:
                score -= 0.30
                break

        # Boost recognizable instrument keywords
        good_words = (
            "bass", "lead", "pad", "piano", "rhodes", "organ",
            "drum rack", "drumrack", "kit", "operator", "wavetable",
            "analog", "electric", "acoustic", "synth", "brass",
            "strings", "guitar", "sax",
        )
        for w in good_words:
            if w in n:
                score += 0.05
                break

        return max(0.0, min(1.0, score))

    def _search_browser(self, query, category, prefer_preset=True, max_results=50):
        """Search the browser by name. Returns up to ``max_results`` matches.

        ``category`` is one of ``all``, ``instruments``, ``sounds``, ``drums``,
        ``audio_effects``, ``midi_effects``. Walks the browser tree depth-first
        with depth limit 6.

        When ``prefer_preset`` is True (default), each match is scored by
        ``_score_browser_item`` (Instrument Rack > Device Preset > Max device >
        bare device > raw sample, with junk-word penalties) and the result list
        is sorted by score descending — so callers that read ``matches[0]``
        get the BEST candidate, not the first alphabetical hit.
        """
        try:
            app = self.application()
            if not app or not hasattr(app, "browser") or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            browser = app.browser
            roots = []
            cats = ("instruments", "sounds", "drums", "audio_effects", "midi_effects")
            if category == "all" or category is None:
                for c in cats:
                    if hasattr(browser, c):
                        roots.append((c, getattr(browser, c)))
            elif category in cats and hasattr(browser, category):
                roots.append((category, getattr(browser, category)))
            else:
                raise ValueError("Unknown category: " + str(category))
            query_lc = (query or "").lower()
            if not query_lc:
                raise ValueError("query must be non-empty")
            matches = []
            # We over-collect by 2x so the score-based sort has a real shot at
            # finding the best item — otherwise we'd hit max_results during
            # the walk and miss good candidates that come later alphabetically.
            walk_cap = max_results * 2 if prefer_preset else max_results
            max_depth = 6

            def walk(item, path_parts, depth):
                if len(matches) >= walk_cap or depth > max_depth:
                    return
                try:
                    name = getattr(item, "name", "") or ""
                except Exception:
                    name = ""
                if name and query_lc in name.lower():
                    is_loadable = bool(getattr(item, "is_loadable", False))
                    full_path = "/".join(path_parts + [name])
                    score = self._score_browser_item(name, full_path, is_loadable)
                    matches.append({
                        "name": name,
                        "uri": getattr(item, "uri", None),
                        "path": full_path,
                        "is_loadable": is_loadable,
                        "score": score,
                    })
                    if len(matches) >= walk_cap:
                        return
                children = getattr(item, "children", None)
                if children:
                    for child in children:
                        walk(child, path_parts + [name] if name else path_parts, depth + 1)

            for root_name, root_item in roots:
                walk(root_item, [root_name], 0)
                if len(matches) >= walk_cap:
                    break

            if prefer_preset:
                matches.sort(key=lambda m: m["score"], reverse=True)
                matches = matches[:max_results]

            return {
                "query": query,
                "category": category,
                "match_count": len(matches),
                "truncated": len(matches) >= max_results,
                "matches": matches,
            }
        except Exception as e:
            self.log_message("Error searching browser: " + str(e))
            raise

    # Maps a logical role to category roots and keyword filters used by
    # _browse_for_role to surface the BEST candidates from the user's library.
    _ROLE_BROWSE_PLAN = {
        "drums": {
            "categories": ["drums", "instruments"],
            "include_keywords": ["drum rack", "kit", "drums"],
            "exclude_keywords": ["hit", "oneshot", "one shot", "one-shot", "crash", "ride", "tom", "snare drum"],
        },
        "bass": {
            "categories": ["instruments", "sounds"],
            "include_keywords": ["bass"],
            "exclude_keywords": ["bass drum", "bass hit"],
        },
        "lead": {
            "categories": ["instruments", "sounds"],
            "include_keywords": ["lead", "synth lead"],
            "exclude_keywords": [],
        },
        "keys": {
            "categories": ["instruments", "sounds"],
            "include_keywords": ["piano", "rhodes", "electric", "organ", "key"],
            "exclude_keywords": ["bass"],
        },
        "pad": {
            "categories": ["instruments", "sounds"],
            "include_keywords": ["pad", "atmosphere"],
            "exclude_keywords": [],
        },
        "brass": {
            "categories": ["instruments", "sounds"],
            "include_keywords": ["brass", "trumpet", "horn", "sax"],
            "exclude_keywords": [],
        },
        "guitar": {
            "categories": ["instruments", "sounds"],
            "include_keywords": ["guitar"],
            "exclude_keywords": ["bass"],
        },
    }

    def _browse_for_role(self, role, max_results=15):
        """Walk the browser specifically looking for instruments suited to
        a logical role (drums / bass / lead / keys / pad / brass / guitar).

        Each role has a curated list of category roots, include keywords, and
        exclude keywords. Items must (a) be loadable, (b) match at least one
        include keyword in name or path, (c) NOT match any exclude keyword.
        Results are scored by ``_score_browser_item`` and sorted by score.
        """
        try:
            role_l = (role or "").lower()
            if role_l not in self._ROLE_BROWSE_PLAN:
                raise ValueError("Unknown role '{0}'. Known roles: {1}".format(
                    role, sorted(self._ROLE_BROWSE_PLAN.keys())))
            plan = self._ROLE_BROWSE_PLAN[role_l]

            app = self.application()
            if not app or not hasattr(app, "browser") or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            browser = app.browser
            results = []
            seen_uris = set()
            max_depth = 6

            include = [k.lower() for k in plan["include_keywords"]]
            exclude = [k.lower() for k in plan["exclude_keywords"]]

            def matches_filters(name_l, path_l):
                if include and not any(k in name_l or k in path_l for k in include):
                    return False
                if any(k in name_l or k in path_l for k in exclude):
                    return False
                return True

            def walk(item, path_parts, depth):
                if depth > max_depth:
                    return
                try:
                    name = getattr(item, "name", "") or ""
                except Exception:
                    name = ""
                if name:
                    full_path = "/".join(path_parts + [name])
                    name_l = name.lower()
                    path_l = full_path.lower()
                    is_loadable = bool(getattr(item, "is_loadable", False))
                    uri = getattr(item, "uri", None)
                    if is_loadable and uri and uri not in seen_uris and matches_filters(name_l, path_l):
                        score = self._score_browser_item(name, full_path, is_loadable)
                        if score > 0.3:  # quality threshold
                            results.append({
                                "name": name,
                                "uri": uri,
                                "path": full_path,
                                "score": score,
                            })
                            seen_uris.add(uri)
                children = getattr(item, "children", None)
                if children:
                    for child in children:
                        walk(child, path_parts + [name] if name else path_parts, depth + 1)

            for cat in plan["categories"]:
                if hasattr(browser, cat):
                    walk(getattr(browser, cat), [cat], 0)

            results.sort(key=lambda r: r["score"], reverse=True)
            return {
                "role": role_l,
                "match_count": len(results),
                "results": results[:max_results],
            }
        except Exception as e:
            self.log_message("Error browsing for role: " + str(e))
            raise

    def _get_track_devices(self, track_index):
        """List devices on a track with their parameters (raw min/max/value)."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            devices = []
            for device_index, device in enumerate(track.devices):
                params = []
                for p_index, param in enumerate(device.parameters):
                    try:
                        params.append({
                            "index": p_index,
                            "name": param.name,
                            "value": param.value,
                            "min": param.min,
                            "max": param.max,
                            "is_enabled": bool(getattr(param, "is_enabled", True)),
                            "is_quantized": bool(getattr(param, "is_quantized", False)),
                        })
                    except Exception:
                        # Some parameters can throw on access; skip them but
                        # leave a placeholder so the index list stays aligned.
                        params.append({"index": p_index, "name": "<unreadable>", "value": None, "min": None, "max": None})
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device),
                    "parameter_count": len(params),
                    "parameters": params,
                })
            return {
                "track_index": track_index,
                "track_name": track.name,
                "device_count": len(devices),
                "devices": devices,
            }
        except Exception as e:
            self.log_message("Error getting track devices: " + str(e))
            raise

    # ----- Tier 5 arrangement view (BETA, capability-probed) -----

    def _arrangement_capabilities(self):
        """Probe Live's arrangement-view API and cache the result."""
        if hasattr(self, "_arr_caps") and self._arr_caps is not None:
            return self._arr_caps
        caps = {
            "can_duplicate_to_arrangement": False,
            "can_read_arrangement_clips": False,
            "has_cue_points": hasattr(self._song, "cue_points"),
            "has_set_or_delete_cue": hasattr(self._song, "set_or_delete_cue"),
            "has_loop": hasattr(self._song, "loop"),
        }
        # Probe per-track arrangement support against the first track if any
        try:
            if len(self._song.tracks) > 0:
                t = self._song.tracks[0]
                caps["can_duplicate_to_arrangement"] = hasattr(t, "duplicate_clip_to_arrangement")
                caps["can_read_arrangement_clips"] = hasattr(t, "arrangement_clips")
        except Exception:
            pass
        self._arr_caps = caps
        return caps

    def _add_clip_to_arrangement(self, track_index, clip_slot_index, arrangement_time):
        """BETA: copy a session clip onto the arrangement timeline at a given time."""
        try:
            caps = self._arrangement_capabilities()
            if not caps.get("can_duplicate_to_arrangement"):
                raise Exception("This Live version does not expose Track.duplicate_clip_to_arrangement; arrangement insertion not supported")
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_slot_index < 0 or clip_slot_index >= len(track.clip_slots):
                raise IndexError("Clip slot index out of range")
            clip_slot = track.clip_slots[clip_slot_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in source slot")
            track.duplicate_clip_to_arrangement(clip_slot.clip, float(arrangement_time))
            return {
                "track_index": track_index,
                "src_slot": clip_slot_index,
                "arrangement_time": float(arrangement_time),
            }
        except Exception as e:
            self.log_message("Error adding clip to arrangement: " + str(e))
            raise

    def _set_arrangement_loop(self, start, end, loop_on):
        """Set the arrangement loop region. Stable in Live 11+."""
        try:
            if end <= start:
                raise ValueError("end must be greater than start")
            self._song.loop_start = float(start)
            self._song.loop_length = float(end - start)
            self._song.loop = bool(loop_on)
            return {
                "loop_start": self._song.loop_start,
                "loop_length": self._song.loop_length,
                "loop": self._song.loop,
            }
        except Exception as e:
            self.log_message("Error setting arrangement loop: " + str(e))
            raise

    def _add_arrangement_locator_async(self, params, response_queue, cancelled):
        """Add a named locator at the given arrangement time using a chained
        main-thread callback so Live can commit ``current_song_time`` between
        the position write and the ``set_or_delete_cue`` toggle.

        Three closures (this method runs on main thread tick 1):
            Tick 1: snapshot cue times, write current_song_time, schedule tick 2
            Tick 2: call set_or_delete_cue, schedule tick 3
            Tick 3: snapshot-diff to find the new cue, set its name, put result

        Each ``schedule_message(0, ...)`` call yields the main thread back to
        Live, which then has the chance to commit the queued state from the
        previous tick before the next callback runs.
        """
        try:
            target_time_f = float(params.get("time", 0.0))
            name = params.get("name", "")
            caps = self._arrangement_capabilities()
            if not caps.get("has_set_or_delete_cue") or not caps.get("has_cue_points"):
                response_queue.put({"status": "error",
                    "message": "This Live version does not expose cue_points or set_or_delete_cue"})
                return
            song = self._song

            # Quick path: a cue already lives within ~0.05 beats of the target,
            # so rename it rather than toggling (which would delete it).
            for cue in song.cue_points:
                if abs(cue.time - target_time_f) < 0.05:
                    if name:
                        cue.name = name
                    response_queue.put({"status": "success", "result": {
                        "time": cue.time,
                        "name": cue.name,
                        "snapped_from": target_time_f,
                        "snap_distance": abs(cue.time - target_time_f),
                        "created": False,
                    }})
                    return

            # Snapshot existing cue times BEFORE we toggle, so we can spot the
            # new one via diff afterward.
            try:
                before_times = set(round(c.time, 4) for c in song.cue_points)
            except Exception:
                before_times = set()

            # Step 1: write play head position. Live needs a tick to commit it.
            song.current_song_time = target_time_f

            def step2_toggle():
                if cancelled[0]:
                    return
                try:
                    song.set_or_delete_cue()

                    def step3_finalize():
                        if cancelled[0]:
                            return
                        try:
                            new_cue = None
                            for cue in song.cue_points:
                                if round(cue.time, 4) not in before_times:
                                    new_cue = cue
                                    break
                            if new_cue is None:
                                # Fallback: closest cue to target_time within window
                                closest = None
                                closest_dist = float("inf")
                                for cue in song.cue_points:
                                    d = abs(cue.time - target_time_f)
                                    if d < closest_dist:
                                        closest_dist = d
                                        closest = cue
                                if closest is None or closest_dist > 4.0:
                                    response_queue.put({"status": "error",
                                        "message": "Could not locate new cue near time {0}".format(target_time_f)})
                                    return
                                new_cue = closest
                            if name:
                                new_cue.name = name
                            response_queue.put({"status": "success", "result": {
                                "time": new_cue.time,
                                "name": new_cue.name,
                                "snapped_from": target_time_f,
                                "snap_distance": abs(new_cue.time - target_time_f),
                                "created": True,
                            }})
                        except Exception as e:
                            self.log_message("Error in step3_finalize: " + str(e))
                            self.log_message(traceback.format_exc())
                            response_queue.put({"status": "error", "message": str(e)})

                    self.schedule_message(0, step3_finalize)
                except Exception as e:
                    self.log_message("Error in step2_toggle: " + str(e))
                    self.log_message(traceback.format_exc())
                    response_queue.put({"status": "error", "message": str(e)})

            self.schedule_message(0, step2_toggle)
        except Exception as e:
            self.log_message("Error in _add_arrangement_locator_async: " + str(e))
            self.log_message(traceback.format_exc())
            response_queue.put({"status": "error", "message": str(e)})

    def _clear_all_arrangement_locators_async(self, params, response_queue, cancelled):
        """Delete every cue point from the arrangement, one at a time, with
        chained main-thread callbacks so position writes commit before each
        toggle. Each cue takes 3 ticks (write position → toggle → continue),
        so 8 cues = ~24 ticks, plenty of time for Live to process between
        operations."""
        try:
            caps = self._arrangement_capabilities()
            if not caps.get("has_set_or_delete_cue") or not caps.get("has_cue_points"):
                response_queue.put({"status": "error",
                    "message": "This Live version does not expose cue_points or set_or_delete_cue"})
                return
            song = self._song
            try:
                times = [c.time for c in song.cue_points]
            except Exception:
                times = []
            state = {"index": 0, "cleared": 0, "times": times}

            def process_next():
                if cancelled[0]:
                    return
                if state["index"] >= len(state["times"]):
                    response_queue.put({"status": "success", "result": {
                        "cleared": state["cleared"],
                        "remaining": len(song.cue_points),
                    }})
                    return
                t = state["times"][state["index"]]
                state["index"] += 1
                try:
                    song.current_song_time = float(t)

                    def after_position():
                        if cancelled[0]:
                            return
                        try:
                            # Snapshot count so we know if the toggle deleted a cue
                            count_before = len(song.cue_points)
                            song.set_or_delete_cue()

                            def after_toggle():
                                if cancelled[0]:
                                    return
                                try:
                                    if len(song.cue_points) < count_before:
                                        state["cleared"] += 1
                                    process_next()
                                except Exception as e:
                                    response_queue.put({"status": "error", "message": str(e)})

                            self.schedule_message(0, after_toggle)
                        except Exception as e:
                            response_queue.put({"status": "error", "message": str(e)})

                    self.schedule_message(0, after_position)
                except Exception as e:
                    response_queue.put({"status": "error", "message": str(e)})

            process_next()
        except Exception as e:
            self.log_message("Error in _clear_all_arrangement_locators_async: " + str(e))
            self.log_message(traceback.format_exc())
            response_queue.put({"status": "error", "message": str(e)})

    def _get_arrangement_info(self):
        """BETA: report arrangement loop state, song length, and (if supported)
        every track's arrangement clips."""
        try:
            caps = self._arrangement_capabilities()
            song = self._song
            tracks_info = []
            for track_index, track in enumerate(song.tracks):
                clips = []
                arr_clips = getattr(track, "arrangement_clips", None)
                if arr_clips is not None:
                    for clip in arr_clips:
                        try:
                            clips.append({
                                "name": getattr(clip, "name", ""),
                                "start_time": getattr(clip, "start_time", None),
                                "end_time": getattr(clip, "end_time", None),
                                "length": getattr(clip, "length", None),
                            })
                        except Exception:
                            continue
                tracks_info.append({
                    "track_index": track_index,
                    "name": track.name,
                    "arrangement_clip_count": len(clips),
                    "arrangement_clips": clips,
                })
            cue_points = []
            if caps.get("has_cue_points"):
                try:
                    for cue in song.cue_points:
                        cue_points.append({"time": cue.time, "name": cue.name})
                except Exception:
                    pass
            return {
                "capabilities": caps,
                "song_length": getattr(song, "song_length", None),
                "last_event_time": getattr(song, "last_event_time", None),
                "loop": getattr(song, "loop", None),
                "loop_start": getattr(song, "loop_start", None),
                "loop_length": getattr(song, "loop_length", None),
                "cue_points": cue_points,
                "tracks": tracks_info,
            }
        except Exception as e:
            self.log_message("Error getting arrangement info: " + str(e))
            raise

    def _get_browser_item(self, uri, path):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = path.split("/")
                
                # Determine the root based on the first part
                current_item = None
                if path_parts[0].lower() == "nstruments":
                    current_item = app.browser.instruments
                elif path_parts[0].lower() == "sounds":
                    current_item = app.browser.sounds
                elif path_parts[0].lower() == "drums":
                    current_item = app.browser.drums
                elif path_parts[0].lower() == "audio_effects":
                    current_item = app.browser.audio_effects
                elif path_parts[0].lower() == "midi_effects":
                    current_item = app.browser.midi_effects
                else:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    def _load_browser_item(self, track_index, item_uri):
        """Load a browser item onto a track by its URI"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            
            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            
            # Select the track
            self._song.view.selected_track = track
            
            # Load the item
            app.browser.load_item(item)
            
            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories
                categories = [
                    browser_or_item.instruments,
                    browser_or_item.sounds,
                    browser_or_item.drums,
                    browser_or_item.audio_effects,
                    browser_or_item.midi_effects
                ]
                
                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item
                
                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Helper methods
    
    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except:
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0].lower()
            current_item = None
            
            # Check standard categories first
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                # Try to find the category in other browser attributes
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                
                if not found:
                    # If we still haven't found the category, return available categories
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "items": []
                    }
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
