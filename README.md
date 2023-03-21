## Proxmox-load-balancer Pro v0.6.4  

## Please take a look: https://github.com/cvk98/Proxmox-load-balancer/issues/7

If you use this script and it works correctly - please do not be lazy to put a star. This motivates me very much to develop my product. If you lack some functions, write about it. I will try to add them if they fit into the product concept.
	
<strong>Development progress:</strong>
1. <strike>Write a draft script</strike>
2. <strike>Put "break" and "continue" in their places</strike>
3. <strike>Arrange the functions in their places</strike>
4. <strike>Ca</strike>tch bugs
5. <strike>Correct variable names</strike>
6. <strike>Add comments</strike>
7. <strike>Add logging and sending notifications to the mail</strike>
8. <strike>Urgently translate into English</strike>
9. Add a VM selection algorithm for special cases when there is a need for migration, but there is no option that improves the balance	
10. <strike>Test on th</strike>ree clusters

![Excluded px-3](https://user-images.githubusercontent.com/88323643/164393540-9be1f695-59ba-4e96-a629-a9e9fd310795.jpg)

This script is designed to automatically load balance the RAM of the cluster (or part of the cluster) Proxmox.
It does not use the CPU load balancing mechanism. I consider this unnecessary for many reasons, which it is inappropriate to list here.
Unlike https://github.com/cvk98/Proxmox-memory-balancer the algorithm of this script has been significantly changed. 

In particular:
1. Added a list of exclusions for the VMs and nodes.
2. It is now possible to disable LXC migration.
3. You can set the spread range of node loading, at which there is no balancing.
4. The VM selection algorithm for migration has been significantly redesigned (other criteria for evaluating the proposed migration options).
5. This script works constantly and does not finish its work when the balance is reached. Just falls asleep for 5 minutes (can be changed).  
6. Now the script can be deployed automatically (via ansible) to all nodes of the cluster using HA. To do this, set only_on_master: ON in the config. Then it will run only on the master node.

Most likely, the script does not need a root PVE account. You can create a separate account with the necessary rights (not tested). But for those who are worried that the script may harm your cluster, I can say that there is only one POST method used for VM/LXC migration.

### Does not take into account the recommendations of HA!

### Recommendations:
1. **For the migration mechanism to work correctly, a shared storage is required. This can be a CEPH (or other distributed storage) or a storage system connected to all Proxmox nodes.**
2. For a cluster similar in size and composition to the one in the screenshot, the normal value of "deviation" is 4%. This means that with an average load of the cluster (or part of it) the maximum deviation of the RAM load of each node can be 2% in a larger or smaller direction.
Example: cluster load is 50%, the minimum loaded node is 48%, the maximum loaded node is 52%.
Moreover, it does not matter at all how much RAM the node has.
3. Do not set the "deviation" value to 0. This will result in a permanent VM migration at the slightest change to the VM["mem"]. The recommended minimum value is 1% for large clusters with many different VMs. For medium and small clusters 3-5%
4. For the script to work correctly, you need constant access to the Proxmox host. Therefore, I recommend running the script on one of the Proxmox nodes or creating a VM/Lxc in a balanced cluster and configuring the script autorun.
5. To autorun the script on Linux (ubuntu):  
	 `touch /etc/systemd/system/load-balancer.service`  
	 `chmod 664 /etc/systemd/system/load-balancer.service`  
		Add the following lines to it, replacing USERNAME with the name of your Linux user:  
			
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

<i>Tested on Proxmox 7.1-10 virtual environment with more than 400 virtual machines</i>  
**Before using the script, please read the Supplement to the license**

# Changelog:

### 0.6.4 (21.03.23)  
1. fix of an error that occurs when nodes are turned off (thanks to dmitry-ko) 
https://github.com/cvk98/Proxmox-load-balancer/pull/14


### 0.6.3 (07.11.22)  
1. fix bug with lxc migration (thanks to MarcMocker) 
https://github.com/cvk98/Proxmox-load-balancer/pull/11

### 0.6.2 (22.08.22)  
1. Add range generation for vm exclusion (thanks to Azerothian)
https://github.com/cvk98/Proxmox-load-balancer/pull/9

### 0.6.1 (22.06.22)
1. Added the "resume" operation 10 seconds after VM migration. Since sometimes the following situation occurs:
  
  ![image](https://user-images.githubusercontent.com/88323643/175003454-eb7014c7-b6be-401b-9420-956487be0034.png)  

### 0.6.0 (23.05.22)
1. Added a mechanism for checking the launch of the load balancer on the HA cluster master node (thanks to Cylindrical)
https://github.com/cvk98/Proxmox-load-balancer/pull/3
	
### 0.5.2 (20.05.22)  
1. Minor improvements suggested by Cylindric regarding cluster health check

### 0.5.1 (18.05.22)  
1. If the cluster has been balanced for the last 10 attempts, the "operational_deviation" parameter is reduced by 2 or 4 or 8 times with some probability.  
	
### 0.5.0 (04.05.22)  
1. Added email notification about critical events  	
	
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

**If you have any exceptions, please write about them in https://github.com/cvk98/Proxmox-load-balancer/issues. I'll try to help you.**

If you want to support the author, you can do it using <b>Etherium</b> by sending a donation to <b>0x1Ee280393C04c8534D36170BF47AD199742579C5</b>
