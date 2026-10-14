# ShipMBLang Core Language Contract

This document is the ShipMBLang-facing contract for source text that lowers
through ShipMBLang Core into ShipMBLang bytecode.

ShipMBLang has two separate layers:

- **Core source** is the readable, line-oriented language users and tools inspect.
- **ShipMBLang bytecode** is the canonical runtime instruction stream emitted by
  the compiler. Bytecode operation names are lowercase canonical names generated
  from English semantics, and those names may change while the source contract
  stays stable.

`architecture |> show` belongs to compile/debug output only. It can display a
partial architecture with diagnostics, but it is not emitted as runtime bytecode.

## Source Shape

Core source is line-oriented to match English sentence structure. Blank lines
are cosmetic and never create scope.

Indentation defines scope and structure for functions, classes, methods,
interfaces, types, device declarations, and object-oriented bodies. Comments use
`#` only.

Accepted:

```shiplang
use shipmb

fn start_controller(device):
  bridge device <-> shipmb.vision using "grpc"
  device |> capability "scan_frame" native
```

Rejected:

```shiplang
use shipmb; fn start_controller(device): bridge device <-> shipmb.vision
// comments cannot use double slash
/* block comments are not part of Core */
```

## Imports And `use`

ShipMB device needs, libraries, device families, and dependencies map to `use`.
Use `from` when pulling a capability, library, or device-family member from a
namespace.

Accepted:

```shiplang
use shipmb
use vision from embedded
use tv_pack from shipmblang
use gpio from embedded
camera = shipmb.vision
```

Rejected:

```shiplang
import shipmb
use vision in embedded
use vision, from embedded
```

Target-language imports may still appear in program-model sections when the
source is describing another language:

```shiplang
target language "python"
import "math"
from "collections" import ["Counter"]
```

## Declarations

First-class declarations are the declarations Core understands: functions,
classes, types, device functions, devices, and supported program-model
declarations. Unknown declarations are hard errors.

Declarations follow the compiler's fixed declaration order. Name resolution is
order-insensitive within the compilation unit in the C#/Java style, so later
methods and functions may be called earlier. Runtime effects still execute in
bytecode order.

Exact declarations merge. Unnecessary duplicates warn. Syntax errors and
compile errors fail compilation.

Accepted:

```shiplang
call boot_device with camera

fn boot_device(device):
  device |> capability "power_on" native

class camera_controller:
  property active_device
  method start(device):
    call boot_device with device

type telemetry_packet:
  field device_id: string
  field frame_count: int
```

Rejected:

```shiplang
widget camera_controller:
  field device_id

fn boot-device(device):
  pass
```

`widget` is not a Core declaration family. `boot-device` is a filename-style
identifier, not a function identifier.

## Identifiers And Paths

Identifiers use `snake_case` by default. Dots access modules or namespaces.
Slashes identify file paths. Kebab-case is reserved for URLs and filenames.
Namespaces prevent conflicts between capabilities or libraries with the same
plain name.

Accepted:

```shiplang
camera_controller = shipmb.vision.camera
profile_path = "configs/vision-profile.json"
use control_panel from "https://shipmb.dev/device-families/control-panel"
```

Rejected:

```shiplang
CameraController = shipmb/vision/camera
profilePath = "configs/vision_profile.json"
```

## Values And Lists

Quoted values are string literals. Bare identifiers are references or
properties. Numbers and booleans are bare. Only plain quoted literals are in
scope for now.

Inline lists use canonical comma-separated Core syntax. A list may also be
declared first and populated later with `append` as the canonical Core verb.
Trailing commas are strictly disallowed.

Accepted:

```shiplang
camera_id = "front-door"
enabled = true
retry_count = 3
source_device = camera_controller

providers = [native_camera, opencv_bridge, browser_camera]
routes = []
routes append "local"
routes append "fallback"
```

Rejected:

```shiplang
camera_id = front-door
providers = [native_camera, opencv_bridge,]
message = "hello ${name}"
```

## Deterministic Options

Flags or options that affect a device family or user communication must be
explicit in source. The compiler may fill legal defaults into bytecode and
normalize equivalent source spellings, but it must not infer privacy, transport,
family, or user-notification choices that change observable behavior.

Accepted:

```shiplang
use embedded
interface operator_console:
  mode "client"
  notify_user true
  privacy "local_only"
```

Rejected:

```shiplang
interface operator_console:
  mode "client"
```

The rejected form omits deterministic user-communication policy.

## Bridges And Protocols

Bridge and protocol validation is required. Invalid protocols or invalid device
pairs are compile errors. Bridges are bidirectional.

Accepted:

```shiplang
bridge camera <-> shipmb.vision using "grpc"
bridge browser <-> shipmb.ui using "websocket"
```

Rejected:

```shiplang
bridge camera -> shipmb.vision using "grpc"
bridge camera <-> gpio using "smtp"
```

## Safety Interlocks

Safety interlocks are required where applicable. Missing interlocks are errors.
Policy expressions are allowed when the device or capability needs conditional
approval.

Accepted:

```shiplang
device robot_arm:
  use motion from embedded
  interlock emergency_stop required
  interlock operator_present when speed > 0
  policy allow movement when emergency_stop == false and operator_present == true
```

Rejected:

```shiplang
device robot_arm:
  use motion from embedded
  robot_arm |> capability "move_joint" native
```

## Capabilities And Providers

`native` and its synonyms mean direct device capability. A single capability may
map to multiple providers. Conflicts resolve by explicit priority.

Accepted:

```shiplang
capability scan_frame:
  provider native_camera priority 100 native
  provider opencv_bridge priority 50
  provider browser_camera priority 10
```

Rejected:

```shiplang
capability scan_frame:
  provider native_camera native
  provider opencv_bridge native
```

The rejected form has conflicting providers without priority.

## Architecture Debug

`architecture |> show` can be used by compilers, IDEs, and tests to inspect
partially compiled state with diagnostics. It must not appear in runtime
bytecode.

Accepted:

```shiplang
architecture |> show
```

Runtime bytecode must omit this operation entirely. No bytecode operation name is
reserved for architecture debug output.

## Diagnostics

Diagnostics report multiple errors when possible. Each diagnostic uses a
distinct phase and code, explains what failed, and includes a fix when one is
possible or necessary.

Example:

```json
[
  {
    "phase": "syntax",
    "code": "SYN_TRAILING_COMMA",
    "message": "Inline lists cannot end with a trailing comma.",
    "fix": "Remove the comma after the final list item."
  },
  {
    "phase": "safety",
    "code": "SAFE_MISSING_INTERLOCK",
    "message": "robot_arm.move_joint requires an emergency_stop interlock.",
    "fix": "Add `interlock emergency_stop required` inside the device block."
  }
]
```
