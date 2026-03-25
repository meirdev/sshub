(function () { "use strict"; document.addEventListener("click", function (e) {
const link = e.target.closest(".ssh-connect"); if (!link) return;
e.preventDefault(); const hostId = link.dataset.hostId; window.open( "/ssh/" +
hostId + "/", "ssh_" + hostId, "width=800,height=500", ); }); })();
