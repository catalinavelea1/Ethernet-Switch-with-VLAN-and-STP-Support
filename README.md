# Ethernet-Switch-with-VLAN-and-STP-Support

The project implements a software Ethernet switch in Python that learns MAC addresses and forwards frames between ports. It includes support for VLANs (access and trunk ports, tagged/untagged frames) and a simplified implementation of the Spanning Tree Protocol (STP), used to prevent loops in the network.

-- Switching Table --

When a frame is received, the source MAC address is mapped to the port on which the frame arrived. We extract the rightmost bit of the first octet of the destination address to determine whether unicast or broadcast will be performed.

If the bit has a value of 1, broadcast is performed, meaning the frame is sent to all other ports except the current port. In the case of unicast, an entry for the destination MAC address is searched for in the switching table. If it exists, the frame is forwarded; otherwise, broadcast is performed.

-- VLAN --

We obtain in the `vlans` array the mapping between a port on a switch and the VLAN to which it belongs. If the value at this entry is "T", it means that the respective port is a trunk port, so it can receive and send packets from any VLAN.

When sending a frame, we store the VLAN to which the current port belongs. We construct the tagged and untagged frames to send them after determining the type of port through which the frame will be forwarded.

Using `vlan_id`, we determine whether we need to remove the header of a tagged frame or add it to an untagged frame. If it is different from -1, it means that the frame arrived from a trunk port, so it is already tagged. If the current port is a trunk port, `vlan_id` must not be updated, because we need to preserve the original VLAN to which the frame belongs.

In the frame transmission logic, we incorporate a new function, `send_frame`, which contains the constraints imposed by VLANs:

A packet will be sent through a port if the destination port is either a trunk port or has the same associated VLAN as the source port.

Depending on the type of destination port, we send a tagged frame (for trunk) or an untagged frame.

-- STP --

Initially, each switch believes it is the root bridge, so we set the switch IDs and ports accordingly.

We check every received frame to determine whether it is a BPDU, in which case it will be processed without being forwarded. For every frame, before transmission, we check the status of the port through which we want to send it, to ensure that it is not blocked.

The `process_bpdu` function is used to process BPDUs sent by the root bridge on all trunk ports. The root bridge sends BPDUs to other switches. If a switch with a lower priority is found, it becomes the root bridge and the variables must be updated. The port through which we discover the root bridge becomes the root port.

In the second case, we receive information about the already known root bridge. It will not be changed, but it is possible to find paths with a lower cost.

If we receive information about the switch we are currently on, we block the port because it may be part of a loop.

If we receive information about the root bridge while we are the root bridge, we ensure that all ports remain DESIGNATED.
