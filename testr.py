from pycaw.pycaw import AudioUtilities

# 1. Get the default speakers
device = AudioUtilities.GetSpeakers()

# 2. Get the Volume interface directly from the device object
# In modern pycaw, this is often a property of the wrapper
volume = device.EndpointVolume

# 3. Read current volume (0.0 to 1.0)
current = volume.GetMasterVolumeLevelScalar()
print(f"Current volume: {current:.2f}")

# 4. Set volume to 20%
volume.SetMasterVolumeLevelScalar(0.3, None)
print("Volume set to 30%")