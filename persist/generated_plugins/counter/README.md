# Counter

# Counter

A simple counter plugin for IoX/eisy.

## What it does
- Adds one node, **Counter**, as soon as the plugin starts.
- The counter starts counting immediately, adding 1 every second.
- **State** shows *Started* or *Stopped*.
- **Counter** is a 4-byte unsigned integer (0 to 4,294,967,295). It never goes below 0 and wraps back to 0 after the maximum.
- **Step** is the amount used by the Increment and Decrement buttons. It is an integer from 1 to 10000 (default 1) and can be changed with the **Set Step** command.

## Commands
| Command | Effect |
|---|---|
| Increment | Adds Step to the counter |
| Decrement | Subtracts Step from the counter (stops at 0) |
| Start | Starts the 1-per-second count |
| Stop | Stops the count |
| Set Step | Sets the Step (1-10000) |

## Notes
- The counter and step reset to 0 and 1 whenever the plugin restarts.
- No configuration is required and the plugin does not access eisy programs or nodes.
