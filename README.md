#### <p align="center"> If you have problems with encoding due to the bestconfig library, then use version 0.3.0 of the balancer!

## Proxmox-load-balancer Pro v0.4.2  (<strike>Run in PyCharm</strike>)

<strong>Development progress:</strong>
1. <strike>Write a draft script</strike>
2. <strike>Put "break" and "continue" in their places</strike>
3. <strike>Arrange the functions in their places</strike>
4. <strike>Ca</strike>tch bugs
5. <strike>Correct variable names</strike>
6. <strike>Add comments</strike>
7. <strike>Add logging </strike>and sending notifications to the mail
8. <strike><b>Urgently translate into English</b></strike>
9. <strike>Test on th</strike>ree clusters

![Excluded px-3](https://user-images.githubusercontent.com/88323643/164393540-9be1f695-59ba-4e96-a629-a9e9fd310795.jpg)

This script is designed to automatically load balance the RAM of the cluster (or part of the cluster) Proxmox.
It does not use the CPU load balancing mechanism. I consider this unnecessary for many reasons, which it is inappropriate to list here.
Unlike https://github.com/cvk98/Proxmox-memory-balancer the algorithm of this script has been significantly changed. 

In particular:
1. Added a list of exclusions for the VMs and nodes.
2. It is now possible to disable LXC migration.
3. You can set the spread range of node loading, at which there is no balancing.
4. The VM selection algorithm for migration has been significantly redesigned (other criteria for evaluating the proposed migration options).
5. This script works constantly and does not finish its work when the balance is reached. Just falls asleep for 5 minutes (can be changed)

Most likely, the script does not need a root PVE account. You can create a separate account with the necessary rights (not tested). But for those who are worried that the script may harm your cluster, I can say that there is only one POST method used for VM/LXC migration.

### Recommendations:
1. For a cluster similar in size and composition to the one in the screenshot, the normal value of "deviation" is 4%. This means that with an average load of the cluster (or part of it) the maximum deviation of the RAM load of each node can be 2% in a larger or smaller direction.
Example: cluster load is 50%, the minimum loaded node is 48%, the maximum loaded node is 52%.
Moreover, it does not matter at all how much RAM the node has.
2. Do not set the "deviation" value to 0. This will result in a permanent VM migration at the slightest change to the VM["mem"]. The recommended minimum value is 1% for large clusters with many different VMs. For medium and small clusters 3-5%
3. For the script to work correctly, you need constant access to the Proxmox host. Therefore, I recommend running the script on one of the Proxmox nodes or creating a VM/Lxc in a balanced cluster and configuring the script autorun.
4. To autorun the script on Linux (ubuntu):  
	 `touch /etc/systemd/system/load-balancer.service`  
	 `chmod 664 /etc/systemd/system/load-balancer.service`  
		Add the following lines to it:  
			
		[Unit]  
  		Description=Proxmor cluster load-balancer Service  
  		After=network.target  

  		[Service]  
  		Type=simple  
  		User=USERNAME  
		NoNewPrivileges=yes  
  		ExecStart=/home/USERNAME/plb.py  
		WorkingDirectory=/home/USERNAME/  
  		Restart=always  
  		RestartSec=300  

  		[Install]  
 		WantedBy=multi-user.target  
				
```systemctl daemon-reload```  
```systemctl start load-balancer.service```  
```systemctl status load-balancer.service```  
```systemctl enable load-balancer.service```  

<i>Tested on Proxmox Virtual Environment 7.1-10 with 400+ virtual</i>  
**Before using the script, please read the Supplement to the license**

# Changelog:
### 0.4.2 (29.04.22)  
1. Removed bestconfig due to encoding issues  
2. Added a check when opening the config	
	
### 0.4.0 (28.04.22)  
1. All settings are placed in the configuration file (config.yaml)
	
### 0.3.0 (22.04.2022)
1. Added logging based on the loguru library (don't forget `pip3 install loguru`). Now logs can be viewed in the console or /var/log/syslog  
2. sys.exit() modes have been changed for the script to work correctly in daemon mode

### 0.2.0 (20.04.2022)
1. All comments and messages are translated into English
2. UTF-8 encoding throughout the document

##### Running the script is tested on:
1. PyCharm 2021+, Python 3.10+, Win10
2. Proxmox LXC Ubuntu 20.04 (1 core, 256 MB, 5GB HDD), Python 3.8+ <strike>(0.4.0)</strike>

**If you have any exceptions, please send them to my email. I'll try to help you.**

If you want to support the author, you can do it using <b>Etherium</b> by sending a donation to <b>0x1Ee280393C04c8534D36170BF47AD199742579C5</b>
