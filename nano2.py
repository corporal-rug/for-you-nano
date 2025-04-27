# -*- coding: utf-8 -*-
# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
## Setup

To install the dependencies for this script, run:

pip install google-genai opencv-python pyaudio pillow mss pyautoit

Before running this script, ensure the GOOGLE_API_KEY environment
variable is set to the api-key you obtained from Google AI Studio.

Important: **Use headphones**. This script uses the system default audio
input and output, which often won't include echo cancellation. So to prevent
the model from interrupting itself it is important that you use headphones.

"""

import os
import sys
import time
import asyncio
import base64
import io
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
import time
import pyaudio
import mss
import PIL.Image
from google import genai
from google.genai import types
import autoit

client = genai.Client(api_key="get your token on website", http_options={'api_version': 'v1alpha'})



# How many seconds between each automatic prompt to do something
AUTO_PROMPTDT = 5
# The prompt message to send every interval
MESSAGE = "Do your job"

def execute(keyname: str, timer: int) -> dict:
    """Keyname is the character or bind you need to press.
    Timer is the amount of times that keybind is pressed using pyautoit. Use THIS to fly the plane."""

    print(f'"{keyname}" {timer} times')
    try:
        robloxWindow = "Roblox" 
        if not autoit.win_exists(robloxWindow):
             return {"fail": f"Roblox window '{robloxWindow}' not found"}

        autoit.win_activate(robloxWindow)
        time.sleep(0.05) 
        for i in range(timer):
            autoit.send(keyname)
        return {"status": "done"}



FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

MODEL = "models/gemini-2.0-flash-live-001"
---------------------------------------------------------------
with open("awacs.txt", "r") as file:
    dog = file.read()

CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    system_instruction=types.Content(
        parts=[types.Part.from_text(text=dog)],
        role="user"
    ),
    speech_config=types.SpeechConfig(
        language_code="en-GB",
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Fenrir")
        )
    ),
    tools=[execute],
)
-----------------------------------------------------------
pya = pyaudio.PyAudio()

class AudioLoop:
    def __init__(self):
        self.audio_in_queue = None
        self.out_queue = None
        self.session = None
        self.send_text_task = None
        self.receive_audio_task = None
        self.play_audio_task = None

    async def send_text(self):
        try:
            while True:
                await asyncio.sleep(AUTO_PROMPTDT)
                await self.session.send(input=MESSAGE,end_of_turn=True)
        except asyncio.CancelledError:

            return


    def _get_screen(self):
        sct = mss.mss()
        monitor = sct.monitors[0]

        i = sct.grab(monitor)

        mime_type = "image/jpeg"
        image_bytes = mss.tools.to_png(i.rgb, i.size)
        img = PIL.Image.open(io.BytesIO(image_bytes))

        image_io = io.BytesIO()
        img.save(image_io, format="jpeg")
        image_io.seek(0)

        image_bytes = image_io.read()
        return {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode()}

    async def get_screen(self):
        while True:
            frame = await asyncio.to_thread(self._get_screen)
            if frame is None:
                break

            await asyncio.sleep(1.0)
            await self.out_queue.put(frame)

    async def send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send(input=msg)

    async def listen_audio(self):
        mic_info = pya.get_default_input_device_info()
        self.audio_stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=SEND_SAMPLE_RATE,
            input=True,
            input_device_index=mic_info["index"],
            frames_per_buffer=CHUNK_SIZE,
        )
        kwargs = {"exception_on_overflow": False} if __debug__ else {}
        while True:
            data = await asyncio.to_thread(
                self.audio_stream.read, CHUNK_SIZE, **kwargs
            )
            await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})

    async def receive_audio(self):
        while True:
            turn = self.session.receive()
            async for response in turn:
                if data := response.data:
                    self.audio_in_queue.put_nowait(data)
                    continue
                if text := response.text:
                    print(text, end="")


            while not self.audio_in_queue.empty():
                self.audio_in_queue.get_nowait()

    async def play_audio(self):
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
        )
        while True:
            bytestream = await self.audio_in_queue.get()
            await asyncio.to_thread(stream.write, bytestream)

    async def run(self):
        try:
            async with (
                client.aio.live.connect(model=MODEL, config=CONFIG) as session,
                asyncio.TaskGroup() as tg,
            ):
                self.session = session

                self.audio_in_queue = asyncio.Queue()
                self.out_queue = asyncio.Queue(maxsize=5)


                send_text_task = tg.create_task(self.send_text())
                tg.create_task(self.send_realtime())
                tg.create_task(self.listen_audio())

                tg.create_task(self.get_screen())

                tg.create_task(self.receive_audio())
                tg.create_task(self.play_audio())

                await send_text_task
                raise asyncio.CancelledError("Loop end")

        except asyncio.CancelledError:
            pass
        except ExceptionGroup as EG:
            self.audio_stream.close()
            traceback.print_exception(EG)


if __name__ == "__main__":
    main = AudioLoop()
    asyncio.run(main.run())
