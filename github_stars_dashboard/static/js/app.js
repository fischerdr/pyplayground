// GitHub Stars Dashboard - Frontend Application

// Global state
let allRepositories = [];
let allCategories = [];
let allActivity = [];

// API base URL
const API_BASE = '';

// Utility functions
function formatNumber(num) {
    return new Intl.NumberFormat().format(num);
}

function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// API call wrapper
async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });

        if (!response.ok) {
            throw new Error(`API Error: ${response.statusText}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API call failed:', error);
        throw error;
    }
}

// Update dashboard stats
async function updateDashboard() {
    try {
        const stats = await apiCall('/api/stats');
        
        document.getElementById('total-repos').textContent = formatNumber(stats.total_repos);
        document.getElementById('total-stars').textContent = formatNumber(stats.total_stars);
        document.getElementById('active-repos').textContent = formatNumber(stats.active_repos);
        document.getElementById('total-categories').textContent = formatNumber(stats.categories_count);

        renderCategoryChart(stats.categories);
    } catch (error) {
        console.error('Failed to update dashboard:', error);
    }
}

// Render category chart
function renderCategoryChart(categories) {
    const container = document.getElementById('category-chart');
    
    if (!categories || categories.length === 0) {
        container.innerHTML = '<p class="empty-message">No categories yet</p>';
        return;
    }

    const maxCount = Math.max(...categories.map(c => c.count));
    const maxStars = Math.max(...categories.map(c => c.total_stars));

    let html = '<div class="category-bars">';
    
    categories.forEach(category => {
        const widthPercent = (category.count / maxCount) * 100;
        const starsWidthPercent = (category.total_stars / maxStars) * 100;
        
        html += `
            <div class="category-bar">
                <div class="category-name">${category.name}</div>
                <div class="bar-container">
                    <div class="bar-repos" style="width: ${widthPercent}%">
                        ${category.count} repos
                    </div>
                </div>
                <div class="bar-container">
                    <div class="bar-stars" style="width: ${starsWidthPercent}%">
                        ${formatNumber(category.total_stars)} stars
                    </div>
                </div>
            </div>
        `;
    });
    
    html += `
        <div class="legend">
            <span class="legend-item"><div class="legend-color repos"></div> Repositories</span>
            <span class="legend-item"><div class="legend-color stars"></div> Stars</span>
        </div>
    `;
    
    container.innerHTML = html;
}

// Render repositories table
async function renderRepositories(repos = null) {
    const data = repos || allRepositories;
    const tbody = document.getElementById('repos-tbody');
    
    if (!data || data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-message">No repositories found</td></tr>';
        return;
    }

    let html = '';
    data.forEach(repo => {
        const isActive = repo.active ? 'Yes' : 'No';
        const activeClass = repo.active ? 'active' : 'inactive';
        
        html += `
            <tr data-id="${repo.id}">
                <td>
                    <a href="https://github.com/${repo.owner}/${repo.name}" target="_blank">
                        ${repo.owner}/${repo.name}
                    </a>
                </td>
                <td>${repo.language || '-'}</td>
                <td>${formatNumber(repo.stars)}</td>
                <td><span class="badge">${repo.category || 'Uncategorized'}</span></td>
                <td><span class="status ${activeClass}">${isActive}</span></td>
                <td class="actions">
                    <button class="btn-icon-btn edit-btn" onclick="editRepository(${repo.id})" title="Edit">
                        ✏️
                    </button>
                    <button class="btn-icon-btn delete-btn" onclick="deleteRepository(${repo.id})" title="Delete">
                        🗑️
                    </button>
                </td>
            </tr>
        `;
    });
    
    tbody.innerHTML = html;
}

// Filter and sort repositories
function filterAndSortRepositories() {
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    const categoryFilter = document.getElementById('category-filter').value;
    const sortBy = document.getElementById('sort-select').value;

    let filtered = allRepositories.filter(repo => {
        const matchesSearch = !searchTerm || 
            repo.owner.toLowerCase().includes(searchTerm) || 
            repo.name.toLowerCase().includes(searchTerm);
        
        const matchesCategory = !categoryFilter || repo.category === categoryFilter;
        
        return matchesSearch && matchesCategory;
    });

    filtered.sort((a, b) => {
        switch (sortBy) {
            case 'stars':
                return b.stars - a.stars;
            case 'name':
                return a.owner.localeCompare(b.owner) || a.name.localeCompare(b.name);
            case 'updated':
                return new Date(b.updated_at) - new Date(a.updated_at);
            default:
                return 0;
        }
    });

    renderRepositories(filtered);
}

// Render categories list
async function renderCategories(categories = null) {
    const data = categories || allCategories;
    const container = document.getElementById('categories-list');
    
    if (!data || data.length === 0) {
        container.innerHTML = '<p class="empty-message">No categories found</p>';
        return;
    }

    let html = '<div class="categories-grid">';
    
    data.forEach(category => {
        html += `
            <div class="category-card">
                <h3>${category.name}</h3>
                <p class="category-pattern">Pattern: ${category.pattern}</p>
                <div class="category-stats">
                    <span class="stat">${category.repo_count} repositories</span>
                    <span class="stat">${formatNumber(category.total_stars)} stars</span>
                </div>
            </div>
        `;
    });
    
    html += '</div>';
    container.innerHTML = html;
}

// Render activity feed
async function renderActivity(activity = null) {
    const data = activity || allActivity;
    const container = document.getElementById('activity-list');
    
    if (!data || data.length === 0) {
        container.innerHTML = '<p class="empty-message">No recent activity</p>';
        return;
    }

    let html = '<div class="activity-items">';
    
    data.forEach(item => {
        html += `
            <div class="activity-item">
                <div class="activity-icon">
                    ${item.type === 'sync' ? '🔄' : '⭐'}
                </div>
                <div class="activity-content">
                    <p class="activity-text">${item.message}</p>
                    <span class="activity-time">${formatDate(item.timestamp)}</span>
                </div>
            </div>
        `;
    });
    
    html += '</div>';
    container.innerHTML = html;
}

// Populate category filter dropdown
function populateCategoryFilter() {
    const select = document.getElementById('category-filter');
    const categories = new Set(allRepositories.map(r => r.category).filter(Boolean));
    
    select.innerHTML = '<option value="">All Categories</option>';
    
    categories.forEach(category => {
        const option = document.createElement('option');
        option.value = category;
        option.textContent = category;
        select.appendChild(option);
    });
}

// Load all data
async function loadData() {
    try {
        const [repos, categories, activity] = await Promise.all([
            apiCall('/api/repositories'),
            apiCall('/api/categories'),
            apiCall('/api/activity/recent')
        ]);

        allRepositories = repos;
        allCategories = categories;
        allActivity = activity;

        updateDashboard();
        renderRepositories(repos);
        populateCategoryFilter();
        renderCategories(categories);
        renderActivity(activity);
    } catch (error) {
        console.error('Failed to load data:', error);
        showError('Failed to load data. Please refresh the page.');
    }
}

// Sync repositories
async function syncRepositories() {
    const btn = document.getElementById('sync-btn');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span><span>Syncing...</span>';
    
    try {
        await apiCall('/api/sync', { method: 'POST' });
        await sleep(500);
        await loadData();
        showNotification('Sync completed successfully!', 'success');
    } catch (error) {
        console.error('Sync failed:', error);
        showError('Sync failed. Please try again.');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// Add repository modal
function openAddModal() {
    document.getElementById('add-repo-modal').style.display = 'flex';
}

function closeAddModal() {
    document.getElementById('add-repo-modal').style.display = 'none';
    document.getElementById('add-repo-form').reset();
}

// Handle add repository form
document.getElementById('add-repo-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const owner = document.getElementById('owner').value;
    const repo = document.getElementById('repo').value;
    
    try {
        await apiCall('/api/repositories', {
            method: 'POST',
            body: JSON.stringify({ owner, name: repo })
        });
        
        closeAddModal();
        await loadData();
        showNotification('Repository added successfully!', 'success');
    } catch (error) {
        console.error('Failed to add repository:', error);
        showError('Failed to add repository. Please check the owner and name.');
    }
});

// Delete repository
async function deleteRepository(id) {
    if (!confirm('Are you sure you want to delete this repository?')) {
        return;
    }
    
    try {
        await apiCall(`/api/repositories/${id}`, { method: 'DELETE' });
        await loadData();
        showNotification('Repository deleted successfully!', 'success');
    } catch (error) {
        console.error('Failed to delete repository:', error);
        showError('Failed to delete repository.');
    }
}

// Edit repository (placeholder - could be implemented)
async function editRepository(id) {
    const repo = allRepositories.find(r => r.id === id);
    if (!repo) return;
    
    const newOwner = prompt('Update owner:', repo.owner);
    if (newOwner === null) return;
    
    const newRepo = prompt('Update repository name:', repo.name);
    if (newRepo === null) return;
    
    try {
        await apiCall(`/api/repositories/${id}`, {
            method: 'PUT',
            body: JSON.stringify({ 
                owner: newOwner, 
                name: newRepo,
                category: repo.category 
            })
        });
        
        await loadData();
        showNotification('Repository updated successfully!', 'success');
    } catch (error) {
        console.error('Failed to update repository:', error);
        showError('Failed to update repository.');
    }
}

// Navigation
function setupNavigation() {
    document.querySelectorAll('nav a').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = link.getAttribute('href').split('#')[1];
            
            document.querySelectorAll('.section').forEach(section => {
                section.classList.remove('active');
            });
            
            document.querySelectorAll('nav a').forEach(navLink => {
                navLink.classList.remove('active');
            });
            
            const targetSection = document.getElementById(targetId);
            if (targetSection) {
                targetSection.classList.add('active');
            }
            link.classList.add('active');
            
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    });
}

// Event listeners
function setupEventListeners() {
    // Sync button
    document.getElementById('sync-btn').addEventListener('click', syncRepositories);
    
    // Add repository button
    document.getElementById('add-repo-btn').addEventListener('click', openAddModal);
    
    // Close modal
    document.querySelector('.close').addEventListener('click', closeAddModal);
    
    // Close modal when clicking outside
    window.addEventListener('click', (e) => {
        const modal = document.getElementById('add-repo-modal');
        if (e.target === modal) {
            closeAddModal();
        }
    });
    
    // Search input
    document.getElementById('search-input').addEventListener('input', filterAndSortRepositories);
    
    // Category filter
    document.getElementById('category-filter').addEventListener('change', filterAndSortRepositories);
    
    // Sort select
    document.getElementById('sort-select').addEventListener('change', filterAndSortRepositories);
}

// Notification system
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 25px;
        background: ${type === 'success' ? '#4CAF50' : '#f44336'};
        color: white;
        border-radius: 4px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

function showError(message) {
    showNotification(message, 'error');
}

// Initialize application
document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupEventListeners();
    loadData();
    
    // Auto-refresh every 60 seconds
    setInterval(() => {
        loadData();
    }, 60000);
});

// Make functions available globally for inline event handlers
window.editRepository = editRepository;
window.deleteRepository = deleteRepository;
