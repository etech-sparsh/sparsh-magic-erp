import React from 'react';
import TaskListView from '../components/tasks/TaskListView';

const DeletedTasks = () => (
  <TaskListView
    scope="deleted"
    heading="Deleted Tasks"
    subheading="Soft-deleted tasks — restore or leave archived"
    emptyMessage="No deleted tasks."
    allowCreate={false}
    splitByRecurrence
  />
);

export default DeletedTasks;
