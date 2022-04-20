# Proxmox-load-balancer Pro v0.2.0  (<strike>run from PyCharm</strike>)

<strong>Development progress:</strong>
1. <strike>Write a draft script</strike>
2. <strike>Put "break" and "continue" in their places</strike>
3. <strike>Arrange the functions in their places</strike>
4. <strike>Ca</strike>tch bugs
5. <strike>Correct variable names</strike>
6. <strike>Add comments</strike>
7. Add logging and sending notifications to the mail
8. <strike><b>Urgently translate into English</b></strike>
9. <strike>Test on th</strike>ree clusters

![Excluded px-3](https://user-images.githubusercontent.com/88323643/163580153-76426d78-b537-4159-82b6-e595a3b5792a.jpg)

This script is designed to automatically load balance the RAM of the cluster (or part of the cluster) Proxmox.
It does not use the CPU load balancing mechanism. I consider this unnecessary for many reasons, which it is inappropriate to list here.
Unlike https://github.com/cvk98/Proxmox-memory-balancer the algorithm of this script has been significantly changed. 

In particular:
1. Added a list of exclusions for the VMs and nodes.
2. It is now possible to disable LXC migration.
3. You can set the spread range of node loading, at which there is no balancing.
4. The VM selection algorithm for migration has been significantly redesigned (other criteria are taken into account).
5. This script works constantly and does not finish its work when the balance is reached. Just falls asleep for 5 minutes (can be changed)

Most likely, the script does not need a root PVE account. You can create a separate account with the necessary rights (not tested). But for those who are worried that the script may harm your cluster, I can say that there is only one POST method used for VM/LXC migration.

# Recommendations:
1. For a cluster similar in size and composition to the one in the screenshot, the normal value of "deviation" is 0.03. This means that with an average load of the cluster (or part of it) the maximum deviation of the RAM load of each node can be 3% in a larger or smaller direction.
Example: cluster load is 50%, the minimum loaded node is 47%, the maximum loaded node is 53%.
Moreover, it does not matter at all how much RAM the node has.
2. For the script to work correctly, you need constant access to the Proxmox host. Therefore, I recommend running the script on one of the Proxmox nodes or creating a VM/Lxc in a balanced cluster and configuring the script autorun.

Tested on Proxmox Virtual Environment 7.1-10 with 400+ virtual
Before using the script, please read the Supplement to the license

# Changelog:
<b>0.2.0</b> (20.04.2022)
1. All comments and messages are translated into English
2. UTF-8 encoding throughout the document (tested on Ubuntu 20.04)

**If you have any exceptions, please send them to my email. I'll try to help you.**

If you want to support the author, you can do it using <b>Etherium</b> by sending a donation to <b>0x1Ee280393C04c8534D36170BF47AD199742579C5</b>
