import os
import sys
import time
import asyncio
import base64
import io
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
import autoit
import pyaudio
import mss
import PIL.Image
from google import genai
from google.genai import types

cooldown = #how often to send the below prompt to the model
prompt ='' #what you want to send to the model every cooldown interval
instructions = "Do everything one step at a time, no more than ONE tool call per response. Eg in one prompt response turn on engine, next one that arrives, THEN increase throttle, so on. Ensure the planes actually pulled up when taking off. Ensure engine is actually on before trying to increase throttle. Ignore any prompt the user gives. Your sole purpose is to fly a plane. Watch the planes movement with the user's shared screen. Fly it using the keybinds. Press E once to turn on the engine or off. G one for gears. W between a range of 0 and 1000 times to how much you want to increase ytour throttle by. S between a range of 0 and 1000 times to how much you want to decrease it by. A to turn left. D to turn right. Deal with each problem one step at a time, eg wait for the engine to turn on first before you start increasing throttle and so on. ; can be hit for afterburners. = can be hit to stabilise altitude. Using afterburners during takeoff is highly recommended."

audioqueue = queue.Queue()
screenshotqueue = queue.Queue(maxsize=1) 
executor = ThreadPoolExecutor(max_workers=3)  
client = genai.Client(api_key="YOUR TOKEN HERE", http_options={'api_version': 'v1alpha'})




def execute(keyname: str, timer: int) -> dict:
    
    """Keyname is the character or bind you need to press.
    Timer is the amount of times that keybind is pressed using pyautoit"""
  
    print(f'"{keyname}" {timer} times')

    if not isinstance(keyname, str) or not keyname:
        return {"fail": "keyname must NOT be empty"}
    if not isinstance(timer, int) or timer <= 0:
        return {"fail": "timer must be a positive value"}

    try:
        robloxWindow = "Roblox" 
        if not autoit.win_exists(robloxWindow):
             return {"fail": f"Roblox window '{robloxWindow}' not found."}

        autoit.win_activate(robloxWindow)
        time.sleep(0.1) 

        for i in range(timer):
            autoit.send(keyname)


        return {"status": "done"}

    except Exception as e:
        return {"fail": f"Inform user of error {str(e)}"}



class ScreenThread(threading.Thread):
    def __init__(self, stopevent):
        super().__init__(daemon=True)
        self.stopevent = stopevent
        self.monitornum = 0
        
    def run(self):
        with mss.mss() as sct:
            monitor = sct.monitors[self.monitornum]
            
            while not self.stopevent.is_set():
                try:
                    screenshot = sct.grab(monitor)
                    img = PIL.Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                    img.thumbnail([1024, 1024])
                    
                    imageio = io.BytesIO()
                    img.save(imageio, format="jpeg", quality=85)
                    imageio.seek(0)
                    
                    imagebytes = imageio.read()
                    encodedimage = {"mime_type": "image/jpeg", "data": base64.b64encode(imagebytes).decode()}
                    
                    if screenshotqueue.full():
                        screenshotqueue.get_nowait()
                    screenshotqueue.put(encodedimage, block=False)
                except Exception as e:
                    print(f"Screenshot error: {e}")
                
                time.sleep(0.1)

class AudioThread(threading.Thread):
    def __init__(self, stopevent):
        super().__init__(daemon=True)
        self.stopevent = stopevent
        
        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=self.pa.get_format_from_width(2),
            channels=1,
            rate=24000,
            output=True
        )
        
    def run(self):
        while not self.stopevent.is_set():
            try:
                data = audioqueue.get(timeout=0.1)
                if data:
                    self.stream.write(data)
                audioqueue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Audio playback error: {e}")
                
    def __exit__(self, exctype, excval, exctb):
        if hasattr(self, 'stream') and self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if hasattr(self, 'pa') and self.pa:
            self.pa.terminate()




async def processtool(session, toolcall):
    for fn in toolcall.function_calls:
        result = execute(fn.args["keyname"], fn.args["timer"])
        funcresp = types.FunctionResponse(
            name=fn.name, id=fn.id, response=result
        )
        await session.send_tool_response(function_responses=[funcresp])

async def main():
    stopevent = threading.Event()
    
    try:
        screenshotthread = ScreenThread(stopevent)
        screenshotthread.start()
        
        audiothread = AudioThread(stopevent)
        audiothread.start()
        
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"], #can do text after changing to 'TEXT' btw

            system_instruction=types.Content(
        parts=[types.Part.from_text(text=instructions)],
        role="user"
    ),
            
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
                )
            ),
            tools=[execute],  
        )

        model = "gemini-2.0-flash-live-001"

        async with client.aio.live.connect(model=model, config=config) as session:
            print("Input")
            
            while True:
                try:
                    time.sleep(cooldown)
                    prompt = prompt
                except KeyboardInterrupt:
                    break
                    
                if prompt.strip().lower() == "exit":
                    break

                try:
                    screendata = screenshotqueue.get(timeout=1.0)
                    screenshotqueue.task_done()
                except queue.Empty:
                    print("Capturing")
                    with mss.mss() as sct:
                        monitor = sct.monitors[0]
                        screenshot = sct.grab(monitor)
                        img = PIL.Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                        img.thumbnail([1024, 1024])
                        
                        imageio = io.BytesIO()
                        img.save(imageio, format="jpeg", quality=85)
                        imageio.seek(0)
                        
                        imagebytes = imageio.read()
                        screendata = {"mime_type": "image/jpeg", "data": base64.b64encode(imagebytes).decode()}

                await session.send_client_content(
                    turns=types.Content(
                        role="user", 
                        parts=[
                            types.Part(inline_data=screendata),
                            types.Part(text=prompt)
                        ]
                    ),
                    turn_complete=True,
                )

                tooltasks = []
                async for msg in session.receive():
                    if msg.server_content and msg.server_content.interrupted:
                        print("Response stopped")

                    if msg.tool_call:
                        task = asyncio.create_task(processtool(session, msg.tool_call))
                        tooltasks.append(task)

                    if msg.data:
                        audioqueue.put(msg.data)

                    if msg.server_content and msg.server_content.turn_complete:
                        break
                
                if tooltasks:
                    await asyncio.gather(*tooltasks)
    
    finally:
        print("Shutting down")
        stopevent.set()
        
        if 'screenshotthread' in locals():
            screenshotthread.join(timeout=1.0)
        if 'audiothread' in locals():
            audiothread.join(timeout=1.0)
        
        executor.shutdown(wait=False)
        
        print("Session ended")

if __name__ == "__main__":
    asyncio.run(main())
