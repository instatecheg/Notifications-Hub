frappe.ui.form.on("Hub Message Log", {
	refresh(frm) {
		if (frm.doc.status === "Sent") return;
		frm.add_custom_button(__("Retry"), () =>
			frm.call({ doc: frm.doc, method: "retry" }).then(r => {
				frappe.show_alert({
					message: __("Retry completed. Status: {0}", [r.message]),
					indicator: r.message === "Sent" ? "green" : "red",
				});
				frm.reload_doc();
			}));
	},
});
