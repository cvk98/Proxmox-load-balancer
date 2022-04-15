# Proxmox-load-balancer
<i>in progress...</i>

<strong>Development progress:</strong>
1. <strike>Write a draft script</strike>
2. <strike>Put "break" and "continue" in their places</strike>
3. <strike>Arrange the functions in their places</strike>
4. <strike>Ca</strike>tch bugs
5. <strike>Correct variable names</strike>
6. <strike>Add comments</strike>
7. Add logging and sending notifications to the mail
8. <strike>Translate in</strike>to English
9. <strike>Test on th</strike>ree clusters

![Excluded px-3](https://user-images.githubusercontent.com/88323643/163580153-76426d78-b537-4159-82b6-e595a3b5792a.jpg)

This script is designed to automatically load balance the RAM of the cluster (or part of the cluster) Proxmox.
It does not use the CPU load balancing mechanism. I consider this unnecessary for many reasons, which it is inappropriate to list here.
Unlike https://github.com/cvk98/Proxmox-memory-balancer the algorithm of this script has been significantly changed. 

In particular:
1. Added a list of exceptions for VM and node.
2. It is now possible to disable LXC migration.
3. You can set the spread range of node loading, at which there is no balancing.
4. The VM selection algorithm for migration has been significantly redesigned (other criteria are taken into account).
5. This script works constantly and does not finish its work when the balance is reached. Just falls asleep for 5 minutes (can be changed)

Tested on Proxmox Virtual Environment 7.1-10 with 400+ virtual
