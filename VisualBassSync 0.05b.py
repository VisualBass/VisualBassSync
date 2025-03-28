import pygame
import sounddevice as sd
import numpy as np
import colorsys
import tkinter as tk
from tkinter import ttk
import logging
import sys
import time
from queue import Queue
import math
from collections import deque
from lifxlan import LifxLAN, Light, WorkflowException

logging.basicConfig(level=logging.INFO)


# -----------------------------
#Version 0.05b
# -----------------------------

# -----------------------------
# LIFX Constants and Setup
# -----------------------------
LIFX_IP = ""  # IP address of your LIFX light
LIFX_MAC = ""  # MAC address of your LIFX light
lifx = LifxLAN()
bulb = None
#bulb = Light(LIFX_MAC, LIFX_IP)  # Use the specific IP and MAC to control the light

# -----------------------------
# CONSTANTS for Audio Processing
# -----------------------------
RATE = 44100
BUFFER = 128
NOISE_FLOOR = -100

TARGET_FREQS = [35, 40, 45, 50]
PRECOMPUTED_RFFT_FREQS = np.fft.rfftfreq(BUFFER, 1.0 / RATE)

SMOOTHING_WINDOW = 10
smoothing_buffer = deque(maxlen=SMOOTHING_WINDOW)

current_gain_db_smoothed = NOISE_FLOOR
glow_value = 0.0  # Visual brightness (0 to 1)
hue_value = 1.0 / 3.0  # Starting hue (green)

# Modes
# -----------------------------
# Modes
# -----------------------------
available_modes = ["polygon", "both", "db meters", "gravity", "waveform", "radial"]

current_mode_index = 0
visualization_mode = available_modes[current_mode_index]
slider_active = False

WINDOW_WIDTH = 900
WINDOW_HEIGHT = 600
# These globals will be recalculated on resize:
MARGIN = 60
METER_WIDTH = 50
TEXT_PADDING = 8
GLOW_WIDTH = 4
BRIGHTNESS_FONT_SIZE = 56

WAVEFORM_POINTS = 128
WAVEFORM_SMOOTHING_FACTOR = 0.025
WAVEFORM_SENSITIVITY = 1.0
control_waveform_points = WAVEFORM_POINTS

# Additional control variables
manual_hue = False  # When True, use fixed hue value
control_sensitivity = 1.0
control_brightness_floor = 0.1  # as factor between 0 and 1

# New globals for menu editing of hue and cycle rate:
editing_hue = False
hue_input = ""
editing_cycle_rate = False
cycle_rate_input = ""
manual_hue_value = 0.0  # 0 means auto-cycle; else fixed hue (0.0 to 1.0)
cycle_rate = 0.0003  # Hue cycle rate when auto-cycling
hue = 0

# Global for storing the latest audio data for waveform:
latest_audio_data = None

audio_queue = Queue(maxsize=16)
last_update_time = time.time()
last_packet_time = time.time()
UPDATE_INTERVAL = 1.0 / 240.0
PACKET_SEND_INTERVAL = 0.009

# Cube & Polygon Constants
cube_vertices = []  # To be initialized later
DEFAULT_SCALE_FACTOR = 100
MAX_SCALE_FACTOR = 6.0
ALPHA_CONSTANT = 157.50

#Orb Rending
ORB_AMOUNT = 50
ESCAPE_MODE = False
SHAKE_INTENSITY = 5

#Waveform Rending
waveform_buffers = []  # To be initialized

# Base dimensions for scaling menus
BASE_WIDTH = 900
BASE_HEIGHT = 600

OFFSCREEN_WIDTH = 900
OFFSCREEN_HEIGHT = 600
pygame_surface = None

# -----------------------------
# Constants for Radial dB Meters
# -----------------------------

# General Constants
DEFAULT_NUM_BARS = 30  # Number of bars in the radial dB meter
DEFAULT_BAR_WIDTH = 5  # Width of each bar in the radial meter
DEFAULT_MAX_BAR_LENGTH = 150  # Maximum length for the bars
DEFAULT_RADIUS = 200  # Radius where the bars will be drawn
BOUNCE_INTENSITY = 10  # Intensity for the bounce effect on the bars
INNER_CIRCLE_RADIUS = 50  # Radius of the inner circle in the center of the radial meter
OUTLINE_THICKNESS = 3  # Thickness of the circle outline

# Side dB Meter Constants
SIDE_METER_WIDTH = 50  # Width of the dB meters on the sides (left and right)
SIDE_METER_MAX_HEIGHT = 300  # Maximum height for the side dB meters
ANGLE_INCREMENT = 12  # Angle increment between each bar in degrees (spread across 360 degrees)
TRIANGLE_SIZE = 15  # Size of triangles if used for decoration (not used here but for reference)


# -----------------------------
# FPS Visibility Control
# -----------------------------
show_fps = True  # Initially, FPS is visible


# -----------------------------
# FPS Drawing Function
# -----------------------------
def draw_fps():
    fps_rect = None
    if show_fps:
        fps = int(clock.get_fps())
        fps_text = font.render(f"FPS: {fps}", True, (255, 255, 255))
        fps_rect = fps_text.get_rect(topright=(WINDOW_WIDTH - 10, 10))

        # Adding 10 pixels around the text for the clickable area
        fps_rect.inflate_ip(10, 10)  # Inflate the rectangle by 10px in all directions

        # Draw FPS text
        screen.blit(fps_text, fps_rect)

    # Return the clickable area (either with or without the text)
    return fps_rect  # Always return the area, even if FPS is not visible

# -----------------------------
# Helper Functions for Scaling and Offscreen Surface
# -----------------------------
def update_offscreen_surface(width, height):
    global pygame_surface
    pygame_surface = pygame.Surface((width, height))


def update_meter_dimensions():
    global MARGIN, METER_WIDTH, TEXT_PADDING, GLOW_WIDTH
    width_factor = WINDOW_WIDTH / BASE_WIDTH
    height_factor = WINDOW_HEIGHT / BASE_HEIGHT
    scale = min(width_factor, height_factor)
    MARGIN = int(60 * scale)
    METER_WIDTH = int(50 * scale)
    TEXT_PADDING = int(8 * scale)
    GLOW_WIDTH = int(4 * scale)


# -----------------------------
# Dummy Smoothing Functions
# -----------------------------
def smooth_db_value(new_db, smoothing_factor=0.2):
    global current_gain_db_smoothed
    current_gain_db_smoothed = smoothing_factor * new_db + (1 - smoothing_factor) * current_gain_db_smoothed
    return current_gain_db_smoothed


def smooth_brightness(val, min_val, rate):
    return max(val, min_val)


# -----------------------------
# FFT-Based Target Frequency Detection
# -----------------------------
def detect_frequencies(data, rate, target_freqs):
    try:
        data = np.ascontiguousarray(data)
        n = len(data)
        if n == BUFFER:
            fft_data = np.abs(np.fft.rfft(data))
            freqs = PRECOMPUTED_RFFT_FREQS
        else:
            fft_data = np.abs(np.fft.rfft(data))
            freqs = np.fft.rfftfreq(n, 1 / rate)
        detected_values = []
        for target_freq in target_freqs:
            target_index = np.argmin(np.abs(freqs - target_freq))
            detected_values.append(fft_data[target_index])
        return max(detected_values)
    except Exception as e:
        logging.error(f"Error in detect_frequencies: {e}")
        return 0


# -----------------------------
# Minimal Audio Callback
# -----------------------------
def audio_callback(indata, frames, time_info, status):
    try:
        if status:
            logging.warning(status)
        data = indata[:, 0].copy()
        if not audio_queue.full():
            audio_queue.put(data)
    except Exception as e:
        logging.error(f"Error in audio_callback: {e}")


MIN_DB = -100
current_gain_db = MIN_DB
current_decay_rate = 5
MAX_DECAY_RATE = 10
DECAY_RAMP_UP_INTERVAL = 1
last_decay_ramp_up_time = time.time()


def apply_decay():
    global current_gain_db, current_decay_rate, last_decay_ramp_up_time
    if time.time() - last_decay_ramp_up_time >= DECAY_RAMP_UP_INTERVAL:
        current_decay_rate = min(current_decay_rate + 1, MAX_DECAY_RATE)
        last_decay_ramp_up_time = time.time()
    current_gain_db -= current_decay_rate
    if current_gain_db < MIN_DB:
        current_gain_db = MIN_DB


# -----------------------------
# Process Audio Queue on Main Thread
# -----------------------------
BRIGHTNESS_GAIN = 1.6  # Boost factor for brightness/glow calculation


def process_audio_queue(dt):
    global waveform_data, latest_audio_data, glow_value, last_update_time, last_packet_time, hue_value
    global current_gain_db, smoothing_buffer, left_channel_amplitude, right_channel_amplitude
    try:
        while not audio_queue.empty():
            audio_data = audio_queue.get()
            waveform_data = audio_data
            latest_audio_data = audio_data.copy()

            current_time = time.time()

            # If stereo (more than one channel), compute separate amplitudes
            if audio_data.ndim > 1 and audio_data.shape[1] >= 2:
                left_channel_amplitude = np.max(np.abs(audio_data[:, 0]))
                right_channel_amplitude = np.max(np.abs(audio_data[:, 1]))
                # Combine channels by averaging for overall detection:
                combined_audio = np.mean(audio_data, axis=1)
            else:
                combined_audio = audio_data
                left_channel_amplitude = np.max(np.abs(audio_data))
                right_channel_amplitude = np.max(np.abs(audio_data))

            # dB reading based on peak amplitude from the combined signal
            peak_value = np.max(np.abs(combined_audio))
            display_db = 20 * np.log10(peak_value) if peak_value > 0 else -100
            smooth_db_value(display_db)

            # Brightness/glow computed from FFT-based detection on the combined signal
            detection_value = detect_frequencies(combined_audio, RATE, TARGET_FREQS)
            smoothing_buffer.append(detection_value)
            smoothed_value = np.mean(smoothing_buffer) if smoothing_buffer else 0
            new_glow_value = min((smoothed_value * BRIGHTNESS_GAIN / 100) * control_sensitivity, 1.0)

            if current_time - last_update_time >= UPDATE_INTERVAL:
                last_update_time = current_time
            glow_value = new_glow_value

            if current_time - last_packet_time >= PACKET_SEND_INTERVAL:
                send_lifx_color(glow_value, hue_value)
                last_packet_time = current_time
    except Exception as e:
        logging.error(f"Error in process_audio_queue: {e}")


# -----------------------------
# Corrected LIFX Color Sending Function
# -----------------------------
def send_lifx_color(glow, hue, retries=3):
    # If no light is available, skip sending color.
    if bulb is None:
        logging.warning("No LIFX bulb available; skipping color update.")
        return

    brightness = max(int(glow * control_sensitivity * 65535), int(control_brightness_floor * 65535))
    lifx_hue = int(hue * 65535) % 65535
    saturation = 65535
    kelvin = 3500
    for attempt in range(retries):
        try:
            bulb.set_color([lifx_hue, saturation, brightness, kelvin])
            logging.info(f"Sent LIFX color: hue={lifx_hue}, brightness={brightness}")
            return
        except Exception as e:
            logging.error(f"Error on attempt {attempt + 1}: {e}")
            time.sleep(0.1)
    logging.error(f"Failed to send color to LIFX after {retries} attempts")


# -----------------------------
# Tkinter Device Selector
# -----------------------------
def select_device_tk(devices_list):
    selected_index = None

    def on_select():
        nonlocal selected_index
        selection = combo.get()
        selected_index = int(selection.split(":")[0])
        root.destroy()

    root = tk.Tk()
    root.title("Select Microphone Device")
    tk.Label(root, text="Select a microphone input device:").pack(padx=10, pady=5)
    device_options = [f"{i}: {name}" for i, name in devices_list]
    combo = ttk.Combobox(root, values=device_options, state="readonly", width=50)
    combo.pack(padx=10, pady=5)
    combo.current(0)
    tk.Button(root, text="Select", command=on_select).pack(pady=10)
    root.mainloop()
    return selected_index


all_devices = sd.query_devices()
mic_devices = [(i, d['name']) for i, d in enumerate(all_devices) if d['max_input_channels'] > 0]
if not mic_devices:
    print("No microphone input devices found. Exiting.")
    sys.exit(1)
device_index = select_device_tk(mic_devices)
print(f"Selected microphone device index: {device_index}")

# -----------------------------
# Start Audio Stream
# -----------------------------
try:
    stream = sd.InputStream(
        device=device_index,
        samplerate=RATE,
        blocksize=BUFFER,
        channels=1,
        callback=audio_callback
    )
    stream.start()
    print("Audio stream started.")
except Exception as e:
    print("Failed to start audio stream:", e)
    sys.exit(1)

# -----------------------------
# Menu Constants & Variables
# -----------------------------
MENU_BUTTON_WIDTH = 100
MENU_BUTTON_HEIGHT = 40
MENU_BUTTON_MARGIN = 20

MENU_PANEL_WIDTH = 150
MENU_PANEL_HEIGHT = 160  # Increased to accommodate 4 fields
MENU_PANEL_BG_COLOR = (50, 50, 50)
MENU_PANEL_ALPHA = 200

MENU_FONT_SIZE = 18
MENU_FONT_COLOR = (255, 255, 255)

# These rects will be updated on resize.
menu_button_rect = pygame.Rect(0, 0, 0, 0)
menu_panel_rect = pygame.Rect(0, 0, 0, 0)
# Define four fields: Mode, Hue, Cycle Rate, Brightness Slider.
mode_field_rect = pygame.Rect(0, 0, 0, 0)
hue_field_rect = pygame.Rect(0, 0, 0, 0)
cycle_rate_field_rect = pygame.Rect(0, 0, 0, 0)
brightness_slider_rect = pygame.Rect(0, 0, 0, 0)

menu_font = None
brightness_font = None
menu_open = False

# -----------------------------
# Menu Fade & Editing Variables
# -----------------------------
MENU_FADE_IN_SPEED = 600
MENU_FADE_OUT_SPEED = 600
menu_alpha = 0
editing_brightness_floor = False
brightness_floor_input = ""
editing_hue = False
hue_input = ""
editing_cycle_rate = False
cycle_rate_input = ""


# -----------------------------
# Update Menu & Meter Dimensions
# -----------------------------
def update_menu_dimensions():
    global MENU_BUTTON_WIDTH, MENU_BUTTON_HEIGHT, MENU_BUTTON_MARGIN
    global MENU_PANEL_WIDTH, MENU_PANEL_HEIGHT
    global menu_button_rect, menu_panel_rect, mode_field_rect, hue_field_rect, cycle_rate_field_rect, brightness_slider_rect
    global MENU_FONT_SIZE, BRIGHTNESS_FONT_SIZE, menu_font, brightness_font

    width_factor = WINDOW_WIDTH / BASE_WIDTH
    height_factor = WINDOW_HEIGHT / BASE_HEIGHT

    MENU_BUTTON_WIDTH = int(100 * width_factor)
    MENU_BUTTON_HEIGHT = int(40 * height_factor)
    MENU_BUTTON_MARGIN = int(20 * height_factor)
    MENU_PANEL_WIDTH = int(150 * width_factor)
    MENU_PANEL_HEIGHT = int(160 * height_factor)

    MENU_FONT_SIZE = int(18 * height_factor)
    BRIGHTNESS_FONT_SIZE = int(56 * height_factor)
    menu_font = pygame.font.SysFont("Arial", MENU_FONT_SIZE)
    brightness_font = pygame.font.SysFont("Arial", BRIGHTNESS_FONT_SIZE)

    # Adjusting menu button position based on window size
    menu_button_rect = pygame.Rect(WINDOW_WIDTH - MENU_BUTTON_WIDTH - MENU_BUTTON_MARGIN,
                                   WINDOW_HEIGHT - MENU_BUTTON_HEIGHT - MENU_BUTTON_MARGIN,
                                   MENU_BUTTON_WIDTH, MENU_BUTTON_HEIGHT)

    # Adjusting menu panel based on button's position
    menu_panel_rect = pygame.Rect(menu_button_rect.x - (MENU_PANEL_WIDTH - MENU_BUTTON_WIDTH),
                                  menu_button_rect.y - MENU_PANEL_HEIGHT,
                                  MENU_PANEL_WIDTH, MENU_PANEL_HEIGHT)

    # Field positions within the menu panel
    field_padding = int(10 * height_factor)
    field_height = int(30 * height_factor)

    mode_field_rect = pygame.Rect(menu_panel_rect.x + field_padding,
                                  menu_panel_rect.y + field_padding,
                                  MENU_PANEL_WIDTH - 2 * field_padding,
                                  field_height)
    hue_field_rect = pygame.Rect(menu_panel_rect.x + field_padding,
                                 mode_field_rect.bottom + field_padding,
                                 MENU_PANEL_WIDTH - 2 * field_padding,
                                 field_height)
    cycle_rate_field_rect = pygame.Rect(menu_panel_rect.x + field_padding,
                                        hue_field_rect.bottom + field_padding,
                                        MENU_PANEL_WIDTH - 2 * field_padding,
                                        field_height)
    brightness_slider_rect = pygame.Rect(menu_panel_rect.x + field_padding,
                                         cycle_rate_field_rect.bottom + field_padding,
                                         MENU_PANEL_WIDTH - 2 * field_padding,
                                         field_height)

# -----------------------------
# Pygame Initialization & Setup
# -----------------------------
pygame.init()
pygame.font.init()
screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("Reactive dB Meters - Hidden Below Noise Floor")
clock = pygame.time.Clock()
font = pygame.font.SysFont("Arial", 20)
brightness_font = pygame.font.SysFont("Arial", BRIGHTNESS_FONT_SIZE)

# Initialize menu dimensions at startup (manual call here)
update_menu_dimensions()  # Initialize menu dimensions at startup
update_meter_dimensions()  # Initialize meter dimensions at startup

# -----------------------------
# Cube/Polygon / Gravity / Waveform Functions (unchanged)
# -----------------------------
def draw_meter_with_glow(target, rect, draw_color, glow_width):
    glow_surf = pygame.Surface((rect.width + 2 * glow_width, rect.height + 2 * glow_width), pygame.SRCALPHA)
    inner_rect = pygame.Rect(glow_width, glow_width, rect.width, rect.height)
    pygame.draw.rect(glow_surf, draw_color, inner_rect)
    for i in range(1, glow_width + 1):
        alpha = int(255 * (1 - i / glow_width) * 0.3)
        glow_color = (draw_color[0], draw_color[1], draw_color[2], alpha)
        outline_rect = inner_rect.inflate(i * 2, i * 2)
        pygame.draw.rect(glow_surf, glow_color, outline_rect, 1)
    target.blit(glow_surf, (rect.x - glow_width, rect.y - glow_width))


def init_cube():
    global cube_vertices
    cube_vertices = [
        np.matrix([-1, -1, 1]),
        np.matrix([1, -1, 1]),
        np.matrix([1, 1, 1]),
        np.matrix([-1, 1, 1]),
        np.matrix([-1, -1, -1]),
        np.matrix([1, -1, -1]),
        np.matrix([1, 1, -1]),
        np.matrix([-1, 1, -1])
    ]


def draw_cube(screen, center_x, center_y, rotation_x, rotation_y, rotation_z, scale, line_color):
    projection_matrix = np.matrix([[1, 0, 0],
                                   [0, 1, 0]])
    projected_points = []
    for point in cube_vertices:
        rotated_point = np.dot(rotation_z, point.reshape((3, 1)))
        rotated_point = np.dot(rotation_y, rotated_point)
        rotated_point = np.dot(rotation_x, rotated_point)
        z = rotated_point[2].item() + 5
        if z == 0:
            z = 0.1
        perspective_scale = scale / z
        projected_2d = np.dot(projection_matrix, rotated_point)
        x = int(projected_2d[0].item() * perspective_scale) + center_x
        y = int(projected_2d[1].item() * perspective_scale) + center_y
        projected_points.append([x, y])
        pygame.draw.circle(screen, line_color, (x, y), 5)

    def connect_points(i, j):
        pygame.draw.line(screen, line_color,
                         (projected_points[i][0], projected_points[i][1]),
                         (projected_points[j][0], projected_points[j][1]), 2)

    for p in range(4):
        connect_points(p, (p + 1) % 4)
        connect_points(p + 4, ((p + 1) % 4) + 4)
        connect_points(p, p + 4)


def draw_polygon_mode(screen, glow_value, hue, center_x, center_y):
    if not cube_vertices:
        init_cube()
    center_x, center_y = screen.get_width() // 2, screen.get_height() // 2
    min_dimension = min(screen.get_width(), screen.get_height())
    scale = (DEFAULT_SCALE_FACTOR * (glow_value * MAX_SCALE_FACTOR)) * (min_dimension / 800)
    angle = pygame.time.get_ticks() * 0.0010
    rotation_z = np.matrix([
        [math.cos(angle), -math.sin(angle), 0],
        [math.sin(angle), math.cos(angle), 0],
        [0, 0, 1]
    ])
    rotation_y = np.matrix([
        [math.cos(angle), 0, math.sin(angle)],
        [0, 1, 0],
        [-math.sin(angle), 0, math.cos(angle)]
    ])
    rotation_x = np.matrix([
        [1, 0, 0],
        [0, math.cos(angle), -math.sin(angle)],
        [0, math.sin(angle), math.cos(angle)]
    ])
    brightness = max(glow_value * control_sensitivity, control_brightness_floor)
    r, g, b = colorsys.hsv_to_rgb(hue, 1, brightness)
    line_color = (int(r * 255), int(g * 255), int(b * 255))
    draw_cube(screen, center_x, center_y, rotation_x, rotation_y, rotation_z, scale, line_color)


def pygame_visualizer(internal_width, internal_height):
    update_offscreen_surface(internal_width, internal_height)
    center_x = pygame_surface.get_width() // 2
    center_y = pygame_surface.get_height() // 2
    draw_polygon_mode(pygame_surface, glow_value, hue_value, center_x, center_y)
    return pygame_surface


class Orb:
    def __init__(self, pos, radius):
        self.pos = np.array(pos, dtype=float)
        self.initial_pos = np.array(pos, dtype=float)
        self.radius = radius
        self.opacity = 255
        self.color = (255, 255, 255)

    def draw(self, surface):
        pygame.draw.circle(surface, self.color, (int(self.pos[0]), int(self.pos[1])), int(self.radius))


orbs = []


def init_orbs():
    global orbs
    orbs = []
    for i in range(ORB_AMOUNT):
        side = np.random.choice(["top", "bottom", "left", "right"])
        if side == "top":
            x = np.random.uniform(0, WINDOW_WIDTH)
            y = 0
        elif side == "bottom":
            x = np.random.uniform(0, WINDOW_WIDTH)
            y = WINDOW_HEIGHT
        elif side == "left":
            x = 0
            y = np.random.uniform(0, WINDOW_HEIGHT)
        else:
            x = WINDOW_WIDTH
            y = np.random.uniform(0, WINDOW_HEIGHT)
        orbs.append(Orb((x, y), 5))

# -----------------------------
# Constants for Gravity & Orbs
# -----------------------------
def update_orbs():
    global orbs, base_color
    center_x = WINDOW_WIDTH / 2
    center_y = WINDOW_HEIGHT / 2
    max_distance = min(WINDOW_WIDTH, WINDOW_HEIGHT) // 2
    remaining_orbs = []
    for orb in orbs:
        dx = orb.pos[0] - center_x
        dy = orb.pos[1] - center_y
        distance_from_center = math.sqrt(dx * dx + dy * dy)
        if distance_from_center == 0:
            distance_from_center = 1
        if ESCAPE_MODE:
            orb.pos[0] += np.random.uniform(-SHAKE_INTENSITY, SHAKE_INTENSITY) * glow_value * control_sensitivity
            orb.pos[1] += np.random.uniform(-SHAKE_INTENSITY, SHAKE_INTENSITY) * glow_value * control_sensitivity
        else:
            direction_x = (center_x - orb.pos[0]) / distance_from_center
            direction_y = (center_y - orb.pos[1]) / distance_from_center
            orb.pos[0] += direction_x * (max_distance * (1 - glow_value)) + np.random.uniform(-SHAKE_INTENSITY,
                                                                                              SHAKE_INTENSITY) * glow_value * control_sensitivity
            orb.pos[1] += direction_y * (max_distance * (1 - glow_value)) + np.random.uniform(-SHAKE_INTENSITY,
                                                                                              SHAKE_INTENSITY) * glow_value * control_sensitivity
        orb.pos[0] = max(orb.radius, min(WINDOW_WIDTH - orb.radius, orb.pos[0]))
        orb.pos[1] = max(orb.radius, min(WINDOW_HEIGHT - orb.radius, orb.pos[1]))
        orb.radius = glow_value * 50 * control_sensitivity
        orb.opacity = int(glow_value * 255 * control_sensitivity)
        orb.color = base_color
        if orb.radius >= 1:
            remaining_orbs.append(orb)
    orbs = remaining_orbs


def draw_orbs():
    for orb in orbs:
        orb.draw(screen)

# -----------------------------
# Constants for Waveform
# -----------------------------
WAVEFORM_HEIGHT_SCALE = 0.85  # Maximum fraction of half-screen height used for waveform amplitude

def update_waveform_buffers():
    global waveform_buffers, control_waveform_points
    waveform_buffers = [deque(maxlen=5) for _ in range(control_waveform_points)]


def draw_waveform_mode():
    global latest_audio_data, hue_value, control_brightness_floor, glow_value, control_sensitivity
    try:
        if latest_audio_data is None or len(latest_audio_data) < 2:
            return

        # Get raw waveform data and downsample
        waveform_data = np.nan_to_num(latest_audio_data, nan=0.0)
        downsample_factor = max(1, len(waveform_data) // control_waveform_points)
        downsampled_waveform = waveform_data[::downsample_factor]
        downsampled_waveform = np.nan_to_num(downsampled_waveform, nan=0.0)

        # Smooth the waveform using the waveform_buffers
        for i in range(len(downsampled_waveform)):
            if i < len(waveform_buffers):
                if downsampled_waveform[i] > 0:
                    waveform_buffers[i].append(downsampled_waveform[i])
                smoothed_val = np.mean(waveform_buffers[i])
                downsampled_waveform[i] = (WAVEFORM_SMOOTHING_FACTOR * smoothed_val +
                                           (1 - WAVEFORM_SMOOTHING_FACTOR) * downsampled_waveform[i])

        amplitude_scale = 1.1
        r, g, b = colorsys.hsv_to_rgb((hue_value + 0.1) % 1.0, 1,
                                      max(glow_value * control_sensitivity * amplitude_scale,
                                          control_brightness_floor))
        base_color = (int(r * 255), int(g * 255), int(b * 255))

        num_points = len(downsampled_waveform)
        if num_points < 2:
            return

        # Compute x positions evenly across the screen
        x_step = screen.get_width() / (num_points - 1)
        points = []
        for i in range(num_points):
            x = int(i * x_step)
            # Compute y position: center + scaled amplitude.
            # The maximum displacement is limited by WAVEFORM_HEIGHT_SCALE.
            y_raw = screen.get_height() // 2 + downsampled_waveform[i] * (
                        screen.get_height() // 2) * WAVEFORM_HEIGHT_SCALE * control_sensitivity
            y = int(max(0, min(y_raw, screen.get_height())))  # Clamp to screen
            points.append((x, y))

        height_factor = WINDOW_HEIGHT / BASE_HEIGHT
        line_width = int(min(1 + glow_value * 5, 6) * height_factor)
        for i in range(num_points - 1):
            pygame.draw.line(screen, base_color, points[i], points[i + 1], line_width)
    except Exception as e:
        logging.error(f"Error in draw_waveform_mode: {e}")

# -----------------------------
# Constants for Radial dB Meters
# -----------------------------
DIAMOND_POWER = 80
DIAMOND_SIZE = 35
DRAW_SMALL_TRIANGLES = True
TRIANGLE_1_DISTANCE = 55
TRIANGLE_1_SIZE = 25
NUM_SIDES = 30
BOUNCE_INTENSITY = 10
INNER_CIRCLE_RADIUS = 180
OUTLINE_THICKNESS = 4
ANGLE_INCREMENT = 12

DRAW_SECOND_SMALL_TRIANGLE = True
SECOND_SMALL_TRIANGLE_SIZE = 15
SECOND_SMALL_TRIANGLE_OFFSET = 120

window_width = 800
window_height = 600

BASE_CIRCLE_RADIUS = 220
BASE_BAR_EXTENSION = 240
BAR_OFFSET = -25

# -----------------------------
# Updated draw_separated_diamond (with 45° rotation, mirrored triangles, and inward-facing second triangles)
# -----------------------------
def draw_separated_diamond(center_x, center_y, glow_value):
    # Use current screen dimensions for uniform scaling.
    glow_value = float(glow_value)
    current_width = screen.get_width()
    current_height = screen.get_height()
    scale = min(current_width / BASE_WIDTH, current_height / BASE_HEIGHT)

    # Compute scaled dimensions.
    separation = glow_value * DIAMOND_POWER * scale
    diamond_size = DIAMOND_SIZE * scale
    triangle1_size = TRIANGLE_1_SIZE * scale
    triangle1_distance = TRIANGLE_1_DISTANCE * scale
    second_triangle_size = SECOND_SMALL_TRIANGLE_SIZE * scale
    second_triangle_offset = SECOND_SMALL_TRIANGLE_OFFSET * scale

    # Use hue_value for color (global hue), brightness from glow_value.
    brightness = max(glow_value * control_sensitivity, control_brightness_floor)
    r, g, b = colorsys.hsv_to_rgb(hue_value, 1, brightness)
    diamond_color = (int(r * 255), int(g * 255), int(b * 255))

    # Setup 45° rotation.
    rotation_angle = math.radians(45)
    cos_angle, sin_angle = math.cos(rotation_angle), math.sin(rotation_angle)

    def rotate_point(x, y, cx, cy):
        x -= cx
        y -= cy
        return x * cos_angle - y * sin_angle + cx, x * sin_angle + y * cos_angle + cy

    # Main diamond triangles (4)
    main_triangles = [
        [(center_x, center_y + separation),
         (center_x - diamond_size, center_y + diamond_size + separation),
         (center_x + diamond_size, center_y + diamond_size + separation)],
        [(center_x + separation, center_y),
         (center_x + diamond_size + separation, center_y + diamond_size),
         (center_x + diamond_size + separation, center_y - diamond_size)],
        [(center_x, center_y - separation),
         (center_x - diamond_size, center_y - diamond_size - separation),
         (center_x + diamond_size, center_y - diamond_size - separation)],
        [(center_x - separation, center_y),
         (center_x - diamond_size - separation, center_y + diamond_size),
         (center_x - diamond_size - separation, center_y - diamond_size)]
    ]
    for triangle in main_triangles:
        rotated_triangle = [rotate_point(x, y, center_x, center_y) for x, y in triangle]
        pygame.draw.polygon(screen, diamond_color, rotated_triangle)

    # Small triangles (4, one for each main triangle)
    if DRAW_SMALL_TRIANGLES:
        small_triangles = [
            [(center_x, center_y + separation + triangle1_distance),
             (center_x - triangle1_size, center_y + triangle1_size + separation + triangle1_distance),
             (center_x + triangle1_size, center_y + triangle1_size + separation + triangle1_distance)],
            [(center_x + separation + triangle1_distance, center_y),
             (center_x + triangle1_size + separation + triangle1_distance, center_y + triangle1_size),
             (center_x + triangle1_size + separation + triangle1_distance, center_y - triangle1_size)],
            [(center_x, center_y - separation - triangle1_distance),
             (center_x - triangle1_size, center_y - triangle1_size - separation - triangle1_distance),
             (center_x + triangle1_size, center_y - triangle1_size - separation - triangle1_distance)],
            [(center_x - separation - triangle1_distance, center_y),
             (center_x - triangle1_size - separation - triangle1_distance, center_y + triangle1_size),
             (center_x - triangle1_size - separation - triangle1_distance, center_y - triangle1_size)]
        ]
        for small_triangle in small_triangles:
            rotated_small_triangle = [rotate_point(x, y, center_x, center_y) for x, y in small_triangle]
            pygame.draw.polygon(screen, diamond_color, rotated_small_triangle)

    # Second small triangles (4) that face inward.
    if DRAW_SECOND_SMALL_TRIANGLE:
        # Define apex positions as before.
        second_triangle_apexes = [
            (center_x, center_y + separation + second_triangle_offset),
            (center_x + separation + second_triangle_offset, center_y),
            (center_x, center_y - separation - second_triangle_offset),
            (center_x - separation - second_triangle_offset, center_y)
        ]
        # For each apex, compute a triangle that points inward.
        for apex in second_triangle_apexes:
            # Compute vector from apex to center.
            vx = center_x - apex[0]
            vy = center_y - apex[1]
            length = math.hypot(vx, vy)
            if length == 0:
                ux, uy = 0, 0
            else:
                ux, uy = vx / length, vy / length
            # Set the triangle's height and base width.
            height = second_triangle_size      # distance from apex to base center
            base_width = second_triangle_size * 2  # width of the base
            # The triangle should point inward; use the unit vector (ux,uy) that points from apex to center.
            base_center = (apex[0] - ux * height, apex[1] - uy * height)
            # Perpendicular vector.
            perp = (-uy, ux)
            base_left = (base_center[0] + (base_width / 2) * perp[0], base_center[1] + (base_width / 2) * perp[1])
            base_right = (base_center[0] - (base_width / 2) * perp[0], base_center[1] - (base_width / 2) * perp[1])
            second_triangle_vertices = [apex, base_left, base_right]
            # Rotate the second triangle by 45° for consistency.
            rotated_second_triangle = [rotate_point(x, y, center_x, center_y) for x, y in second_triangle_vertices]
            pygame.draw.polygon(screen, diamond_color, rotated_second_triangle)


# -----------------------------
# draw_circle_outline (Responsive)
# -----------------------------
def draw_circle_outline(center_x, center_y, radius, outline_thickness, outline_color):
    current_width = screen.get_width()
    current_height = screen.get_height()
    scale = min(current_width / BASE_WIDTH, current_height / BASE_HEIGHT)
    points = []
    num_sides = max(int(NUM_SIDES * scale), 30)
    angle_step = 2 * math.pi / num_sides
    radius = float(radius)
    for i in range(num_sides):
        angle = i * angle_step
        x = float(center_x) + radius * math.cos(angle)
        y = float(center_y) + radius * math.sin(angle)
        points.append((x, y))
    pygame.draw.polygon(screen, outline_color, points, int(outline_thickness))


# -----------------------------
# Pygame version of draw_radial_db_meters (Updated, Responsive, 1:1 Scaled with Bounce)
# -----------------------------
def draw_radial_db_meters():
    global latest_audio_data, glow_value, hue_value, control_sensitivity, control_brightness_floor
    try:
        if latest_audio_data is None or len(latest_audio_data) < 2:
            return

        current_width = screen.get_width()
        current_height = screen.get_height()
        scale = min(current_width / BASE_WIDTH, current_height / BASE_HEIGHT)

        fft_data = np.abs(np.fft.fft(latest_audio_data))[:len(latest_audio_data)//2]
        num_bars = DEFAULT_NUM_BARS
        bar_width = int(DEFAULT_BAR_WIDTH * scale)
        max_amplitude = np.max(fft_data) if np.max(fft_data) != 0 else 1
        bar_amplitudes = [amp / max_amplitude for amp in fft_data[:num_bars]]

        brightness = max(glow_value * control_sensitivity, control_brightness_floor)
        r, g, b = colorsys.hsv_to_rgb(hue_value, 1, brightness)
        color = (int(r * 255), int(g * 255), int(b * 255))

        # The starting circle radius expands with glow_value (bounce effect)
        circle_radius = (BASE_CIRCLE_RADIUS + glow_value * BOUNCE_INTENSITY) * scale
        # The maximum extension of the bar (beyond the circle) also bounces
        max_bar_extension = (BASE_BAR_EXTENSION + glow_value * BOUNCE_INTENSITY) * scale

        center_x = current_width // 2
        center_y = current_height // 2

        outline_thickness = int(OUTLINE_THICKNESS * scale)

        # Draw the circle outline exactly at circle_radius
        draw_circle_outline(center_x, center_y, circle_radius, outline_thickness, color)

        # Calculate the starting radius for bars with an offset to create spacing.
        start_radius = circle_radius - (BAR_OFFSET * scale)

        for i in range(num_bars):
            angle = math.radians(i * ANGLE_INCREMENT)
            amplitude = bar_amplitudes[i] * max_amplitude
            db_value = 20 * np.log10(amplitude) if amplitude > 0 else -100
            # Only extend bars if above threshold
            if db_value >= -50:
                bar_length = bar_amplitudes[i] * max_bar_extension
            else:
                bar_length = 0

            # Start the bar at the offset radius
            start_x = int(center_x + start_radius * math.cos(angle))
            start_y = int(center_y + start_radius * math.sin(angle))
            # End point extends outward from the start
            end_x = int(center_x + (start_radius + bar_length) * math.cos(angle))
            end_y = int(center_y + (start_radius + bar_length) * math.sin(angle))
            pygame.draw.line(screen, color, (start_x, start_y), (end_x, end_y), bar_width)

        draw_separated_diamond(center_x, center_y, glow_value)

    except Exception as e:
        logging.error(f"Error in draw_radial_db_meters: {e}")


# -----------------------------
# Menu Drawing & Handling Functions
# -----------------------------
def update_menu_fade(dt):
    global menu_alpha, menu_open
    # Simple fade in/out based on whether the menu is open.
    if menu_open:
        menu_alpha = min(menu_alpha + MENU_FADE_IN_SPEED * dt, 255)
    else:
        menu_alpha = max(menu_alpha - MENU_FADE_OUT_SPEED * dt, 0)


def draw_menu_button():
    button_color = (100, 100, 100, int(menu_alpha))
    button_surf = pygame.Surface((MENU_BUTTON_WIDTH, MENU_BUTTON_HEIGHT), pygame.SRCALPHA)
    button_surf.fill(button_color)
    screen.blit(button_surf, (menu_button_rect.x, menu_button_rect.y))
    button_text = menu_font.render("Menu", True, MENU_FONT_COLOR)
    button_text.set_alpha(int(menu_alpha))
    text_rect = button_text.get_rect(center=menu_button_rect.center)
    screen.blit(button_text, text_rect)


def draw_menu():
    # Draw panel background
    panel_surf = pygame.Surface((MENU_PANEL_WIDTH, MENU_PANEL_HEIGHT), pygame.SRCALPHA)
    panel_color = (MENU_PANEL_BG_COLOR[0], MENU_PANEL_BG_COLOR[1], MENU_PANEL_BG_COLOR[2],
                   int(MENU_PANEL_ALPHA * (menu_alpha / 255)))
    panel_surf.fill(panel_color)
    screen.blit(panel_surf, (menu_panel_rect.x, menu_panel_rect.y))

    # Draw Mode Field (top)
    pygame.draw.rect(screen, (70, 70, 70, int(menu_alpha)), mode_field_rect)
    mode_text = menu_font.render(available_modes[current_mode_index], True, MENU_FONT_COLOR)
    mode_text.set_alpha(int(menu_alpha))
    mode_text_rect = mode_text.get_rect(center=mode_field_rect.center)
    screen.blit(mode_text, mode_text_rect)

    # Hue Field
    pygame.draw.rect(screen, (70, 70, 70, int(menu_alpha)), hue_field_rect)
    # Display either user input or the actual hue value (in manual or automatic mode)
    hue_display = hue_input if editing_hue else f"Hue (0 for auto): {manual_hue_value:.2f}"  # Display as 0.00 format
    hue_text = menu_font.render(hue_display, True, MENU_FONT_COLOR)
    hue_text.set_alpha(int(menu_alpha))
    hue_text_rect = hue_text.get_rect(center=hue_field_rect.center)
    screen.blit(hue_text, hue_text_rect)

    # Draw Cycle Rate Field
    pygame.draw.rect(screen, (70, 70, 70, int(menu_alpha)), cycle_rate_field_rect)
    cycle_rate_display = cycle_rate_input if editing_cycle_rate else f"Cycle Rate: {cycle_rate:.4f}"
    cycle_rate_text = menu_font.render(cycle_rate_display, True, MENU_FONT_COLOR)
    cycle_rate_text.set_alpha(int(menu_alpha))
    cycle_rate_text_rect = cycle_rate_text.get_rect(center=cycle_rate_field_rect.center)
    screen.blit(cycle_rate_text, cycle_rate_text_rect)

    # Draw Brightness Slider Field (bottom)
    pygame.draw.rect(screen, (70, 70, 70, int(menu_alpha)), brightness_slider_rect)
    if editing_brightness_floor:
        input_box_rect = brightness_slider_rect.copy()
        pygame.draw.rect(screen, (50, 50, 50), input_box_rect)
        edit_text = menu_font.render(brightness_floor_input, True, (255, 255, 0))
        edit_text.set_alpha(int(menu_alpha))
        edit_rect = edit_text.get_rect(center=input_box_rect.center)
        screen.blit(edit_text, edit_rect)
    else:
        hf = WINDOW_HEIGHT / BASE_HEIGHT
        knob_radius = int(8 * hf)
        knob_x = brightness_slider_rect.x + int(control_brightness_floor * brightness_slider_rect.width)
        knob_y = brightness_slider_rect.y + brightness_slider_rect.height // 2
        pygame.draw.circle(screen, (200, 200, 200), (knob_x, knob_y), knob_radius)
        label_text = menu_font.render(f"Brightness Floor: {int(control_brightness_floor * 100)}%", True, MENU_FONT_COLOR)
        label_rect = label_text.get_rect(center=(brightness_slider_rect.centerx, brightness_slider_rect.y - int(10 * hf)))
        screen.blit(label_text, label_rect)


def handle_menu_events(event):
    global menu_open, current_mode_index, visualization_mode, orbs
    global slider_active, editing_brightness_floor, brightness_floor_input
    global editing_hue, hue_input, editing_cycle_rate, cycle_rate_input
    global manual_hue_value, cycle_rate, control_brightness_floor
    global show_fps  # Add this global flag for FPS visibility

    if event.type == pygame.MOUSEBUTTONDOWN:
        mx, my = event.pos
        # Check if click is inside the menu (panel or button)
        if menu_panel_rect.collidepoint(mx, my) or menu_button_rect.collidepoint(mx, my):
            menu_open = True
            # Cancel editing for all fields
            editing_hue = False
            editing_cycle_rate = False
            editing_brightness_floor = False
            # Check brightness slider field first.
            if brightness_slider_rect.collidepoint(mx, my):
                if event.button == 1:
                    slider_active = True
                    print("[DEBUG] Brightness slider activated at", event.pos)
                elif event.button == 3:
                    editing_brightness_floor = True
                    brightness_floor_input = ""
            elif mode_field_rect.collidepoint(mx, my):
                current_mode_index = (current_mode_index + 1) % len(available_modes)
                visualization_mode = available_modes[current_mode_index]
                if visualization_mode == "gravity" and not orbs:
                    init_orbs()
            elif hue_field_rect.collidepoint(mx, my):
                editing_hue = True
                hue_input = ""
            elif cycle_rate_field_rect.collidepoint(mx, my):
                editing_cycle_rate = True
                cycle_rate_input = ""
        else:
            menu_open = False

        # Check if click is inside the expanded FPS area (even if it's hidden)
        fps_rect = draw_fps()  # Get the FPS area (draw and get the clickable rect)
        if fps_rect and fps_rect.collidepoint(mx, my):
            show_fps = not show_fps  # Toggle FPS visibility
            print("[DEBUG] FPS visibility toggled!")

    elif event.type == pygame.MOUSEBUTTONUP:
        if event.button == 1:
            slider_active = False

    elif event.type == pygame.MOUSEMOTION:
        if slider_active and not editing_brightness_floor:
            # Debug prints
            print("[DEBUG] Mouse moved:", event.pos)
            print("[DEBUG] Brightness slider rect:", brightness_slider_rect)
            relative_x = event.pos[0] - brightness_slider_rect.x
            new_val = relative_x / brightness_slider_rect.width
            new_val = max(0, min(new_val, 1))
            control_brightness_floor = new_val
            print(f"[DEBUG] control_brightness_floor updated to: {control_brightness_floor}")


# -----------------------------
# Handle Keyboard Events (Including F2 for FPS Toggle)
# -----------------------------
def handle_keyboard_events(event):
    global editing_brightness_floor, brightness_floor_input, control_brightness_floor
    global editing_hue, hue_input, manual_hue_value, manual_hue
    global editing_cycle_rate, cycle_rate_input, cycle_rate
    global show_fps  # Global flag for FPS visibility

    # Handling FPS visibility toggle via F2 key
    if event.type == pygame.KEYDOWN:
        if event.key == pygame.K_F2:
            show_fps = not show_fps  # Toggle FPS visibility when F2 is pressed
            print("[DEBUG] FPS visibility toggled by F2!")

    # Brightness editing
    if editing_brightness_floor:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                s = brightness_floor_input.strip()
                if s.endswith("%"):
                    s = s[:-1].strip()
                try:
                    val = int(s)
                    val = max(0, min(val, 100))
                    control_brightness_floor = val / 100.0
                    brightness_floor_input = f"{val}%"
                except ValueError:
                    brightness_floor_input = f"{int(control_brightness_floor * 100)}%"
                editing_brightness_floor = False
            elif event.key == pygame.K_BACKSPACE:
                brightness_floor_input = brightness_floor_input[:-1]
            else:
                if event.unicode.isdigit():
                    brightness_floor_input += event.unicode
                elif event.unicode == "%" and "%" not in brightness_floor_input:
                    brightness_floor_input += event.unicode

    # Hue editing
    if editing_hue:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                # If "Enter" is pressed, finalize the hue input
                s = hue_input.strip()
                try:
                    val = float(s)
                    # Ensure hue is clamped between 0.0 and 1.0 for HSV range
                    val = max(0.0, min(val, 1.0))  # Clamp the value between 0 and 1
                    manual_hue_value = val  # Store the hue as a float between 0.0 and 1.0
                    manual_hue = (val != 0)  # Set flag to check if it's manual hue
                    print(f"[DEBUG] Manual hue set to {manual_hue_value} (manual_hue={manual_hue})")
                except ValueError:
                    print("[DEBUG] Invalid hue input!")
                editing_hue = False  # Stop editing after hitting Enter
            elif event.key == pygame.K_BACKSPACE:
                hue_input = hue_input[:-1]  # Backspace support
            else:
                if event.unicode.isdigit() or event.unicode == '.':
                    hue_input += event.unicode  # Append input character

    # Cycle rate editing
    if editing_cycle_rate:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                s = cycle_rate_input.strip()
                try:
                    val = float(s)
                    cycle_rate = val
                    print(f"[DEBUG] Cycle rate set to {cycle_rate}")
                except ValueError:
                    print("[DEBUG] Invalid cycle rate input!")
                editing_cycle_rate = False
            elif event.key == pygame.K_BACKSPACE:
                cycle_rate_input = cycle_rate_input[:-1]
            else:
                if event.unicode.isdigit() or event.unicode == '.':
                    cycle_rate_input += event.unicode


# -----------------------------
# Main Loop
# -----------------------------
running = True
update_offscreen_surface(WINDOW_WIDTH, WINDOW_HEIGHT)
if visualization_mode == "polygon":
    if not cube_vertices:
        init_cube()
elif visualization_mode == "waveform":
    update_waveform_buffers()
    draw_waveform_mode()
if visualization_mode == "radial":
    draw_radial_db_meters()

display_glow = 0.0

# -----------------------------
# Main Loop
# -----------------------------
# -----------------------------
# Main Loop
# -----------------------------
while running:
    dt = clock.get_time() / 1000.0  # Delta time for updates
    process_audio_queue(UPDATE_INTERVAL)  # Process the audio queue

    # Update the display glow
    display_glow += 0.05 * (glow_value - display_glow)

    # Check if the mouse is hovering over the menu button or the panel
    mx, my = pygame.mouse.get_pos()
    if menu_button_rect.collidepoint(mx, my) or menu_panel_rect.collidepoint(mx, my):
        menu_open = True
    else:
        menu_open = False

    # Update menu fade based on whether it's open or not
    update_menu_fade(dt)

    # Handle events (mouse clicks, keyboard presses, resizing, etc.)
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.VIDEORESIZE:
            WINDOW_WIDTH, WINDOW_HEIGHT = event.size
            screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE)
            update_offscreen_surface(WINDOW_WIDTH, WINDOW_HEIGHT)
            update_menu_dimensions()
            update_meter_dimensions()
        handle_menu_events(event)
        handle_keyboard_events(event)

    # Clear the screen before drawing new frames
    screen.fill((0, 0, 0))

    # Update the hue value based on the auto-cycle or manual hue value
    if not manual_hue:
        hue_value += cycle_rate
        if hue_value > 1.0:
            hue_value -= 1.0
    else:
        hue_value = manual_hue_value

    # Calculate brightness and corresponding RGB color
    brightness = max(glow_value * control_sensitivity, control_brightness_floor)
    r, g, b = colorsys.hsv_to_rgb(hue_value, 1.0, brightness)
    base_color = (int(r * 255), int(g * 255), int(b * 255))

    # -----------------------------
    # Visualization Mode Drawing
    # -----------------------------
    # Draw visualization based on the selected mode
    if visualization_mode == "polygon":
        poly_surface = pygame_visualizer(OFFSCREEN_WIDTH, OFFSCREEN_HEIGHT)
        poly_scaled = pygame.transform.scale(poly_surface, (WINDOW_WIDTH, WINDOW_HEIGHT))
        screen.blit(poly_scaled, (0, 0))
    elif visualization_mode == "waveform":
        draw_waveform_mode()
    elif visualization_mode == "radial":
        draw_radial_db_meters()  # Draw radial dB meters

    if visualization_mode in ["both", "db meters", "gravity"]:
        # Draw dB meters (if needed)
        bounding_x = MARGIN
        bounding_y = MARGIN
        bounding_w = WINDOW_WIDTH - 2 * MARGIN
        bounding_h = WINDOW_HEIGHT - 2 * MARGIN
        if bounding_w >= 0 and bounding_h >= 0:
            volume_factor = display_glow
            color_factor = max(display_glow, control_brightness_floor)
            brightness_percent = round(color_factor * 100)
            modulated_color = (int(base_color[0] * color_factor),
                               int(base_color[1] * color_factor),
                               int(base_color[2] * color_factor))
            meter_fill_height = int(volume_factor * bounding_h)
            meter_top = (bounding_y + bounding_h) - meter_fill_height

            left_meter_rect = pygame.Rect(bounding_x, meter_top, METER_WIDTH, meter_fill_height)
            right_meter_rect = pygame.Rect(bounding_x + bounding_w - METER_WIDTH, meter_top, METER_WIDTH,
                                           meter_fill_height)
            draw_meter_with_glow(screen, left_meter_rect, modulated_color, GLOW_WIDTH)
            draw_meter_with_glow(screen, right_meter_rect, modulated_color, GLOW_WIDTH)

            db_text_color = (int(255 * color_factor), int(255 * color_factor), int(255 * color_factor))
            db_text = f"{current_gain_db_smoothed:.1f} dB"
            db_surface = font.render(db_text, True, db_text_color)
            text_y = bounding_y + bounding_h + TEXT_PADDING
            left_text_x = left_meter_rect.x + (METER_WIDTH - db_surface.get_width()) / 2
            right_text_x = right_meter_rect.x + (METER_WIDTH - db_surface.get_width()) / 2
            screen.blit(db_surface, (left_text_x, text_y))
            screen.blit(db_surface, (right_text_x, text_y))

            brightness_text = f"Brightness: {brightness_percent}%"
            brightness_surface = brightness_font.render(brightness_text, True, modulated_color)
            brightness_x = (WINDOW_WIDTH - brightness_surface.get_width()) // 2
            brightness_y = 10
            screen.blit(brightness_surface, (brightness_x, brightness_y))

    # Handle gravity mode and orb animations
    if visualization_mode == "gravity":
        if glow_value > 0 and not orbs:
            init_orbs()
        update_orbs()
        draw_orbs()

    # -----------------------------
    # Draw Menu Button & Menu
    # -----------------------------
    draw_menu_button()
    if menu_alpha > 0:
        draw_menu()

    # -----------------------------
    # Draw FPS (top-right corner)
    # -----------------------------
    fps_rect = draw_fps()  # This draws the FPS if visible and returns the clickable area

    # Flip the display (updates the screen)
    pygame.display.flip()
    clock.tick(240)  # Control the frame rate (fps)


stream.stop()
stream.close()
pygame.quit()
