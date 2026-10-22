#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]
    
    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG    
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    # Check for VLAN tag (0x8100 in network byte order is b'\x81\x00')    
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id

def create_vlan_tag(vlan_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used    
    return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)

def send_bpdu(port, root_bridge_id, sender_bridge_id, sender_path_cost):
    dest_mac = bytes.fromhex('0180c2000000')
    src_mac = get_switch_mac()
    
    llc_len = struct.pack('!H', 38)
    llc = struct.pack('!3B', 0x42, 0x42, 0x03)

    bpdu_body = struct.pack('!Q I Q', root_bridge_id, sender_path_cost, sender_bridge_id)
    
    frame = dest_mac + src_mac + llc_len + llc + bpdu_body
    
    send_to_link(port, len(frame), frame)

def process_bpdu(data, interface, port_statuses, own_bridge_id, root_bridge_id, root_path_cost):
    bpdu_data = data[17:]
    
    received_root_id, received_path_cost, sender_bridge_id = struct.unpack('!Q I Q', bpdu_data)
    
    if received_root_id < root_bridge_id:
        # Found a better root bridge
        root_bridge_id = received_root_id
        root_path_cost = received_path_cost + 10
        
        for port in port_statuses:
            # Current port becomes root port
            if port == interface:
                port_statuses[port] = "ROOT"
            elif port_statuses[port] != "DESIGNATED":
                port_statuses[port] = "BLOCKED"
                
    elif received_root_id == root_bridge_id:
        # Update with shortest path towards root bridge
        if port_statuses[interface] == "ROOT" and received_path_cost + 10 < root_path_cost:
            root_path_cost = received_path_cost + 10
        elif received_path_cost > root_path_cost:
            port_statuses[interface] = "DESIGNATED"
    elif sender_bridge_id == own_bridge_id:
        # Possible loop encountered: block port
        port_statuses[interface] = "BLOCKED"
        
    if own_bridge_id == root_bridge_id:
        # Current port is root bridge
        for port in port_statuses:
            port_statuses[port] = "DESIGNATED"
              
    return root_bridge_id, root_path_cost
    

def send_bdpu_every_sec(own_bridge_id, root_bridge_id, interfaces, vlans, port_statuses, root_path_cost):
    while own_bridge_id == root_bridge_id:
        # Only root bridge sends bdpu
        for port in interfaces:
            if vlans[port] == "T":
                send_bpdu(port, root_bridge_id, own_bridge_id, root_path_cost)
        time.sleep(1)

def get_switch_info(switch_id, interfaces_names, vlans):
    file = open(f'configs/switch{switch_id}.cfg', "r")
    lines = file.readlines()
    priority_value = int(lines[0].strip())
    
    for l in lines[1:]:
        interface_name, vlan = l.strip().split()
        if interface_name in interfaces_names:
            vlans[interfaces_names[interface_name]] = vlan
    return priority_value        


def send_frame(out_port, vlans, tagged_frame, untagged_frame, vlan_id, port_statuses):
    
    if port_statuses.get(out_port) == "BLOCKED":
        return
    out_vlan = vlans[out_port]
    
    if out_vlan == "T":
        send_to_link(out_port, len(tagged_frame), tagged_frame)
    elif out_vlan != "T" and int(out_vlan) == vlan_id:
        send_to_link(out_port, len(untagged_frame), untagged_frame)      

def main():
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1    
    switch_id = sys.argv[1]
    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)
    
    MAC_Table = {}
    interfaces_names = {}
    vlans = {}
    port_statuses = {}
    
    for i in interfaces:
        interfaces_names[get_interface_name(i)] = i
    
    priority = get_switch_info(switch_id, interfaces_names, vlans)
    
    own_bridge_id = priority 
    root_bridge_id = priority
    root_path_cost = 0
         
    # Initialize
    for port in interfaces:
        if vlans[port] == "T":
            port_statuses[port] = "BLOCKED"
            
    if priority == root_bridge_id:
        for port in interfaces:
            port_statuses[port] = "DESIGNATED"
    
    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec, 
                        args=(own_bridge_id, root_bridge_id, interfaces, 
                              vlans, port_statuses, root_path_cost))
    t.start()

    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].
        interface, data, length = recv_from_any_link()
        
        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)
        
        dest_mac_str = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac_str = ':'.join(f'{b:02x}' for b in src_mac)
        
        MAC_Table[src_mac_str] = interface
        broadcast_bit = dest_mac[0] & 1
        
        port_vlan = vlans[interface]
        
        if dest_mac_str == "01:80:c2:00:00:00":
            root_bridge_id, root_path_cost = process_bpdu(
                data, interface, port_statuses, own_bridge_id, 
                root_bridge_id, root_path_cost
            )
            continue
            
        if port_statuses.get(interface) != "BLOCKED":       
           
            if (vlan_id == -1):
                # an untagged frame was recieved
                untagged_frame = data
                tagged_frame = data[0:12] + create_vlan_tag(int(port_vlan)) + data[12:]
            else:
                # a tagged frame was recieved
                tagged_frame = data
                untagged_frame = data[0:12] + data[16:] 
            
            if port_vlan != "T":
                vlan_id = int(port_vlan)
            
            if broadcast_bit == 1:
                for o in interfaces:
                    if o != interface:
                        send_frame(o, vlans, tagged_frame, untagged_frame, vlan_id, port_statuses)
            else:
                if dest_mac_str in MAC_Table:
                    o = MAC_Table[dest_mac_str]
                    send_frame(o, vlans, tagged_frame, untagged_frame, vlan_id, port_statuses)
                else:
                    for o in interfaces:
                        if o != interface:
                            send_frame(o, vlans, tagged_frame, untagged_frame, vlan_id, port_statuses)
                            
        # data is of type bytes.
        # send_to_link(i, length, data)
                            

if __name__ == "__main__":
    main()