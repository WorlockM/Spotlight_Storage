let editingBuildId = null;
let pendingExecuteBuildId = null;

const buildsListModal = new bootstrap.Modal(document.getElementById('builds-list-modal'));
const buildEditModal = new bootstrap.Modal(document.getElementById('build-edit-modal'));
const buildExecuteModal = new bootstrap.Modal(document.getElementById('build-execute-modal'));

function openBuildsModal() {
    fetch('/api/builds')
        .then(r => r.json())
        .then(builds => {
            renderBuildsList(builds);
            buildsListModal.show();
        });
}

function renderBuildsList(builds) {
    const container = document.getElementById('builds-list-container');
    if (builds.length === 0) {
        container.innerHTML = '<p class="text-muted text-center">No builds yet. Click "New Build" to create one.</p>';
        return;
    }
    container.innerHTML = builds.map(b => `
        <div class="d-flex align-items-center justify-content-between mb-2 border rounded p-2">
            <span class="fw-semibold">${escapeHtml(b.name)}</span>
            <div>
                <button class="btn btn-outline-success btn-sm pe-2 me-1 btn-execute-build"
                        data-build-id="${b.id}" data-build-name="${escapeHtml(b.name)}">
                    <i data-lucide="hammer" style="width:14px;height:14px;"></i>
                    <span class="ms-1">Execute</span>
                </button>
                <button class="btn btn-outline-primary btn-sm me-1 btn-edit-build" data-build-id="${b.id}">
                    <i data-lucide="pencil" style="width:14px;height:14px;"></i>
                </button>
                <button class="btn btn-outline-danger btn-sm btn-delete-build" data-build-id="${b.id}" data-build-name="${escapeHtml(b.name)}">
                    <i data-lucide="trash" style="width:14px;height:14px;"></i>
                </button>
            </div>
        </div>
    `).join('');
    lucide.createIcons();
}

function openNewBuildModal() {
    editingBuildId = null;
    document.getElementById('build-edit-modal-label').textContent = 'New Build';
    document.getElementById('build-name-input').value = '';
    document.getElementById('build-parts-list').innerHTML = '';
    buildsListModal.hide();
    buildEditModal.show();
}

function openEditBuildModal(buildId) {
    editingBuildId = buildId;
    document.getElementById('build-edit-modal-label').textContent = 'Edit Build';
    fetch(`/api/builds/${buildId}`)
        .then(r => r.json())
        .then(data => {
            fetch('/api/items')
                .then(r => r.json())
                .then(items => {
                    document.getElementById('build-name-input').value = '';
                    document.getElementById('build-parts-list').innerHTML = '';

                    // Find name from fetched items or use fetchedItems global
                    const allItems = (typeof fetchedItems !== 'undefined' && fetchedItems.length > 0)
                        ? fetchedItems : items;

                    const buildItem = allItems.find ? null : null;
                    // We need the build name — fetch from builds list
                    fetch('/api/builds')
                        .then(r => r.json())
                        .then(builds => {
                            const build = builds.find(b => b.id == buildId);
                            if (build) document.getElementById('build-name-input').value = build.name;
                        });

                    data.items.forEach(part => {
                        addPartRow(allItems, part.item_id, part.quantity_needed);
                    });

                    buildsListModal.hide();
                    buildEditModal.show();
                });
        });
}

function addPartRow(items, selectedItemId, qty) {
    const allItems = (items && items.length > 0) ? items
        : (typeof fetchedItems !== 'undefined' ? fetchedItems : []);

    const options = allItems.map(item =>
        `<option value="${item.id}" ${item.id == selectedItemId ? 'selected' : ''}>${escapeHtml(item.name)}</option>`
    ).join('');

    const row = document.createElement('div');
    row.className = 'd-flex align-items-center mb-2 build-part-row';
    row.innerHTML = `
        <select class="form-select me-2 build-part-select">${options}</select>
        <input type="number" class="form-control me-2 build-part-qty" style="width:80px" min="1" value="${qty || 1}">
        <button type="button" class="btn btn-outline-danger btn-sm btn-remove-part">
            <i data-lucide="trash" style="width:14px;height:14px;"></i>
        </button>
    `;
    row.querySelector('.btn-remove-part').addEventListener('click', () => row.remove());
    document.getElementById('build-parts-list').appendChild(row);
    lucide.createIcons();
}

function saveBuild() {
    const name = document.getElementById('build-name-input').value.trim();
    if (!name) {
        alert('Please enter a build name.');
        return;
    }

    const rows = document.querySelectorAll('#build-parts-list .build-part-row');
    const items = Array.from(rows).map(row => ({
        item_id: parseInt(row.querySelector('.build-part-select').value, 10),
        quantity_needed: parseInt(row.querySelector('.build-part-qty').value, 10) || 1
    }));

    const body = { name, items };

    const method = editingBuildId ? 'PUT' : 'POST';
    const url = editingBuildId ? `/api/builds/${editingBuildId}` : '/api/builds';

    fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    })
        .then(r => r.json())
        .then(() => {
            buildEditModal.hide();
            openBuildsModal();
        });
}

function openExecuteModal(buildId, buildName) {
    pendingExecuteBuildId = buildId;
    document.getElementById('build-execute-name').textContent = buildName;
    document.getElementById('build-execute-warnings').classList.add('d-none');
    document.getElementById('build-execute-warnings').textContent = '';

    fetch(`/api/builds/${buildId}`)
        .then(r => r.json())
        .then(data => {
            const partsEl = document.getElementById('build-execute-parts');
            if (data.items.length === 0) {
                partsEl.textContent = 'No parts in this build.';
            } else {
                partsEl.innerHTML = data.items.map(p =>
                    `<span class="me-3">${escapeHtml(p.name)}: <strong>${p.quantity_needed}</strong> (stock: ${p.quantity})</span>`
                ).join('<br>');
            }
            buildExecuteModal.show();
        });
}

function confirmExecute() {
    if (!pendingExecuteBuildId) return;
    fetch(`/api/builds/${pendingExecuteBuildId}/execute`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.warnings && data.warnings.length > 0) {
                const warningsEl = document.getElementById('build-execute-warnings');
                warningsEl.innerHTML = '<strong>Low stock warnings:</strong><br>' +
                    data.warnings.map(w => `${escapeHtml(w.name)}: needed ${w.need}, had ${w.have}`).join('<br>');
                warningsEl.classList.remove('d-none');
                // Reload items in background but keep modal open to show warnings
                if (typeof loadItems === 'function') loadItems();
            } else {
                buildExecuteModal.hide();
                if (typeof loadItems === 'function') loadItems();
            }
            pendingExecuteBuildId = null;
        });
}

function deleteBuild(buildId, buildName) {
    if (!confirm(`Delete build "${buildName}"?`)) return;
    fetch(`/api/builds/${buildId}`, { method: 'DELETE' })
        .then(() => openBuildsModal());
}

// escapeHtml is defined in script.js

// Event wiring
document.getElementById('open-builds-btn').addEventListener('click', openBuildsModal);

document.getElementById('new-build-btn').addEventListener('click', openNewBuildModal);

document.getElementById('add-build-part-btn').addEventListener('click', () => {
    const allItems = typeof fetchedItems !== 'undefined' ? fetchedItems : [];
    addPartRow(allItems, null, 1);
});

document.getElementById('save-build-btn').addEventListener('click', saveBuild);

document.getElementById('confirm-execute-btn').addEventListener('click', confirmExecute);

document.getElementById('builds-list-container').addEventListener('click', function (e) {
    const execBtn = e.target.closest('.btn-execute-build');
    const editBtn = e.target.closest('.btn-edit-build');
    const delBtn = e.target.closest('.btn-delete-build');
    if (execBtn) openExecuteModal(execBtn.dataset.buildId, execBtn.dataset.buildName);
    if (editBtn) openEditBuildModal(editBtn.dataset.buildId);
    if (delBtn) deleteBuild(delBtn.dataset.buildId, delBtn.dataset.buildName);
});
