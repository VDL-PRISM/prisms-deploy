db.deployments.insert({
    name: "Deployment 1",
    active: true,
    sensors: {
        monitora002: {
            name: "Pavithra's Desk",
            inside: true,
            important_measurement: "pm_small"
        },
        monitora004: {
            name: "Phil's Desk",
            inside: true,
            important_measurement: "pm_small"
        },
        monitora005: {
            name: "Bookshelf",
            inside: true,
            important_measurement: "pm_small"
        }
    }
})
