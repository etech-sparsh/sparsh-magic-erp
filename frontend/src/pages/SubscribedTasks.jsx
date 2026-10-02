import React from 'react';
import TaskListView from '../components/tasks/TaskListView';

const SubscribedTasks = () => (
  <TaskListView
    scope="subscribed"
    heading="Subscribed Tasks"
    subheading="Tasks you're kept in the loop on"
    emptyMessage="You're not subscribed to any tasks yet."
    allowCreate={false}
    splitByRecurrence
  />
);

export default SubscribedTasks;
